import MagicString from "magic-string";
import { parseAst } from "vite";
import type { ESTree, Plugin } from "vite";

export const CLIENT_ENTRY_ID = "virtual:belgie-render/client-entry";
export const CLIENT_SOURCE_ID = "virtual:belgie-render/caller";
export const CLIENT_RENDER_ID = "virtual:belgie-render/client-api";

const RESOLVED_CLIENT_ENTRY_ID = `\0${CLIENT_ENTRY_ID}`;
const RESOLVED_CLIENT_SOURCE_ID = `\0${CLIENT_SOURCE_ID}.tsx`;
const RESOLVED_CLIENT_RENDER_ID = `\0${CLIENT_RENDER_ID}`;

type AstNode = ESTree.Node & {
  [key: string]: unknown;
  end: number;
  start: number;
};

type ImportDeclaration = AstNode & {
  source: { value: string };
  specifiers: (AstNode & { local: { name: string }; imported?: { name?: string; value?: string } })[];
};

interface RenderContext {
  source: string;
  url: string;
  version: 1;
}

function isNode(value: unknown): value is AstNode {
  return typeof value === "object" && value !== null && "type" in value && "start" in value && "end" in value;
}

function walk(node: AstNode, visit: (node: AstNode) => boolean | undefined): void {
  if (visit(node) === false) {
    return;
  }
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (isNode(item)) {
          walk(item, visit);
        }
      }
    } else if (isNode(value)) {
      walk(value, visit);
    }
  }
}

function propertyName(node: AstNode): string | undefined {
  const key = node.key;
  if (typeof key !== "object" || key === null) {
    return undefined;
  }
  if ("name" in key && typeof key.name === "string") {
    return key.name;
  }
  if ("value" in key && typeof key.value === "string") {
    return key.value;
  }
  return undefined;
}

function renderImport(source: string): boolean {
  return /^(?:npm:)?@belgie\/render(?:@[^/]+)?$/u.test(source);
}

function importedName(specifier: ImportDeclaration["specifiers"][number]): string | undefined {
  if (specifier.type !== "ImportSpecifier") {
    return undefined;
  }
  return specifier.imported?.name ?? specifier.imported?.value;
}

function collectIdentifiers(node: AstNode): Set<string> {
  const names = new Set<string>();
  walk(node, (child) => {
    if (child.type === "Identifier" && "name" in child && typeof child.name === "string") {
      names.add(child.name);
    }
  });
  return names;
}

function removeObjectProperty(transformed: MagicString, properties: AstNode[], propertyIndex: number): void {
  const property = properties[propertyIndex];
  if (property === undefined) {
    return;
  }
  if (properties.length === 1) {
    transformed.remove(property.start, property.end);
  } else if (propertyIndex === 0) {
    const next = properties[1];
    if (next !== undefined) {
      transformed.remove(property.start, next.start);
    }
  } else {
    const previous = properties[propertyIndex - 1];
    if (previous !== undefined) {
      transformed.remove(previous.end, property.end);
    }
  }
}

function formatImportSpecifier(specifier: ImportDeclaration["specifiers"][number]): string {
  const local = specifier.local.name;
  if (specifier.type === "ImportDefaultSpecifier") {
    return local;
  }
  if (specifier.type === "ImportNamespaceSpecifier") {
    return `* as ${local}`;
  }
  const imported = importedName(specifier) ?? local;
  return imported === local ? imported : `${imported} as ${local}`;
}

function formatImport(source: string, specifiers: ImportDeclaration["specifiers"]): string {
  const defaultSpecifier = specifiers.find((specifier) => specifier.type === "ImportDefaultSpecifier");
  const namespaceSpecifier = specifiers.find((specifier) => specifier.type === "ImportNamespaceSpecifier");
  const namedSpecifiers = specifiers.filter((specifier) => specifier.type === "ImportSpecifier");
  const groups: string[] = [];
  if (defaultSpecifier !== undefined) {
    groups.push(formatImportSpecifier(defaultSpecifier));
  }
  if (namespaceSpecifier !== undefined) {
    groups.push(formatImportSpecifier(namespaceSpecifier));
  }
  if (namedSpecifiers.length > 0) {
    groups.push(`{ ${namedSpecifiers.map(formatImportSpecifier).join(", ")} }`);
  }
  return `import ${groups.join(", ")} from ${JSON.stringify(source)};`;
}

const UNANALYZABLE_PLUGINS_ERROR =
  "@belgie/render: plugins must be declared in a statically analyzable render(...) options object";

function unwrapExpression(node: AstNode): AstNode {
  let current = node;
  while (
    (current.type === "ParenthesizedExpression" ||
      current.type === "TSAsExpression" ||
      current.type === "TSSatisfiesExpression" ||
      current.type === "TSTypeAssertion") &&
    "expression" in current &&
    isNode(current.expression)
  ) {
    current = current.expression;
  }
  return current;
}

function expressionRootName(node: AstNode): string | undefined {
  let current = unwrapExpression(node);
  while (current.type === "MemberExpression" && "object" in current && isNode(current.object)) {
    current = unwrapExpression(current.object);
  }
  if (current.type === "Identifier" && "name" in current && typeof current.name === "string") {
    return current.name;
  }
  return undefined;
}

function isRenderValue(node: AstNode, renderNames: Set<string>, renderNamespaces: Set<string>): boolean {
  const callee = unwrapExpression(node);
  if (callee.type === "Identifier" && "name" in callee && typeof callee.name === "string") {
    return renderNames.has(callee.name);
  }
  if (
    callee.type !== "MemberExpression" ||
    !("computed" in callee) ||
    callee.computed ||
    !("object" in callee) ||
    !isNode(callee.object) ||
    !("property" in callee) ||
    !isNode(callee.property) ||
    callee.property.type !== "Identifier" ||
    !("name" in callee.property) ||
    callee.property.name !== "render"
  ) {
    return false;
  }
  const object = unwrapExpression(callee.object);
  return (
    object.type === "Identifier" &&
    "name" in object &&
    typeof object.name === "string" &&
    renderNamespaces.has(object.name)
  );
}

function isRenderCallee(callee: AstNode, renderNames: Set<string>, renderNamespaces: Set<string>): boolean {
  return isRenderValue(callee, renderNames, renderNamespaces);
}

function allowRenderValueIdentifiers(node: AstNode, allowed: Set<AstNode>): void {
  const unwrapped = unwrapExpression(node);
  if (unwrapped.type === "Identifier") {
    allowed.add(unwrapped);
    return;
  }
  if (unwrapped.type === "MemberExpression" && "object" in unwrapped && isNode(unwrapped.object)) {
    allowRenderValueIdentifiers(unwrapped.object, allowed);
  }
}

function collectRenderAliases(root: AstNode, renderNames: Set<string>, renderNamespaces: Set<string>): Set<string> {
  for (;;) {
    const discovered: string[] = [];
    walk(root, (node) => {
      if (
        node.type !== "VariableDeclarator" ||
        !("id" in node) ||
        !isNode(node.id) ||
        node.id.type !== "Identifier" ||
        !("name" in node.id) ||
        typeof node.id.name !== "string" ||
        !("init" in node) ||
        !isNode(node.init)
      ) {
        return;
      }
      const name = node.id.name;
      if (renderNames.has(name) || renderNamespaces.has(name)) {
        return;
      }
      if (isRenderValue(node.init, renderNames, renderNamespaces)) {
        discovered.push(name);
      }
    });
    if (discovered.length === 0) {
      break;
    }
    for (const name of discovered) {
      renderNames.add(name);
    }
  }

  const reassignedRender = new Set<string>();
  walk(root, (node) => {
    if (node.type === "AssignmentExpression" && "left" in node && isNode(node.left)) {
      const name = expressionRootName(node.left);
      if (name !== undefined && (renderNames.has(name) || renderNamespaces.has(name))) {
        reassignedRender.add(name);
      }
      return;
    }
    if (node.type === "UpdateExpression" && "argument" in node && isNode(node.argument)) {
      const name = expressionRootName(node.argument);
      if (name !== undefined && (renderNames.has(name) || renderNamespaces.has(name))) {
        reassignedRender.add(name);
      }
    }
  });
  return reassignedRender;
}

function collectPatternIdentifiers(node: AstNode, into: Set<AstNode>): void {
  if (node.type === "Identifier") {
    into.add(node);
    return;
  }
  walk(node, (child) => {
    if (child.type === "Identifier") {
      into.add(child);
    }
  });
}

function assertRenderBindingsAnalyzable(
  root: AstNode,
  renderNames: Set<string>,
  renderNamespaces: Set<string>,
  reassignedRender: Set<string>,
): void {
  walk(root, (node) => {
    if (node.type !== "ImportExpression" || !("source" in node) || !isNode(node.source)) {
      return;
    }
    const source = unwrapExpression(node.source);
    if (
      source.type === "Literal" &&
      "value" in source &&
      typeof source.value === "string" &&
      renderImport(source.value)
    ) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
  });

  const bindingIdentifiers = new Set<AstNode>();
  const allowedIdentifiers = new Set<AstNode>();
  walk(root, (node) => {
    if (node.type === "VariableDeclarator" && "id" in node && isNode(node.id)) {
      collectPatternIdentifiers(node.id, bindingIdentifiers);
      if ("init" in node && isNode(node.init) && isRenderValue(node.init, renderNames, renderNamespaces)) {
        allowRenderValueIdentifiers(node.init, allowedIdentifiers);
      }
    }
    if (
      node.type === "CallExpression" &&
      "callee" in node &&
      isNode(node.callee) &&
      isRenderValue(node.callee, renderNames, renderNamespaces)
    ) {
      allowRenderValueIdentifiers(node.callee, allowedIdentifiers);
    }
    if (
      node.type === "ChainExpression" &&
      "expression" in node &&
      isNode(node.expression) &&
      node.expression.type === "CallExpression" &&
      "callee" in node.expression &&
      isNode(node.expression.callee) &&
      isRenderValue(node.expression.callee, renderNames, renderNamespaces)
    ) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
  });

  walk(root, (node) => {
    if (node.type === "ImportDeclaration") {
      return false;
    }
    if (node.type !== "Identifier" || !("name" in node) || typeof node.name !== "string") {
      return;
    }
    if (!renderNames.has(node.name) && !renderNamespaces.has(node.name)) {
      return;
    }
    if (bindingIdentifiers.has(node)) {
      return;
    }
    if (!allowedIdentifiers.has(node) || reassignedRender.has(node.name)) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
  });
}

function markRootReassigned(node: AstNode, reassigned: Set<string>): void {
  const name = expressionRootName(node);
  if (name !== undefined) {
    reassigned.add(name);
  }
}

function recordObjectDeclarator(node: AstNode, objects: Map<string, AstNode>, reassigned: Set<string>): void {
  if (
    node.type !== "VariableDeclarator" ||
    !("id" in node) ||
    !isNode(node.id) ||
    node.id.type !== "Identifier" ||
    !("name" in node.id) ||
    typeof node.id.name !== "string" ||
    !("init" in node) ||
    !isNode(node.init)
  ) {
    return;
  }
  const name = node.id.name;
  const init = unwrapExpression(node.init);
  if (init.type !== "ObjectExpression") {
    return;
  }
  if (objects.has(name)) {
    reassigned.add(name);
  } else {
    objects.set(name, init);
  }
}

function recordBindingMutation(node: AstNode, reassigned: Set<string>): void {
  if (node.type === "AssignmentExpression" && "left" in node && isNode(node.left)) {
    markRootReassigned(node.left, reassigned);
    return;
  }
  if (node.type === "UpdateExpression" && "argument" in node && isNode(node.argument)) {
    markRootReassigned(node.argument, reassigned);
    return;
  }
  if (
    node.type === "CallExpression" &&
    "callee" in node &&
    isNode(node.callee) &&
    node.callee.type === "MemberExpression"
  ) {
    markRootReassigned(node.callee, reassigned);
  }
}

function collectObjectBindings(program: AstNode): { objects: Map<string, AstNode>; reassigned: Set<string> } {
  const objects = new Map<string, AstNode>();
  const reassigned = new Set<string>();
  walk(program, (node) => {
    recordObjectDeclarator(node, objects, reassigned);
    recordBindingMutation(node, reassigned);
  });
  return { objects, reassigned };
}

function resolveObjectExpression(
  node: AstNode,
  objects: Map<string, AstNode>,
  reassigned: Set<string>,
): AstNode | undefined {
  const unwrapped = unwrapExpression(node);
  if (unwrapped.type === "ObjectExpression") {
    return unwrapped;
  }
  if (unwrapped.type === "Identifier" && "name" in unwrapped && typeof unwrapped.name === "string") {
    if (reassigned.has(unwrapped.name)) {
      return undefined;
    }
    return objects.get(unwrapped.name);
  }
  return undefined;
}

function collectPluginPropertiesFromObject(
  object: AstNode,
  objects: Map<string, AstNode>,
  reassigned: Set<string>,
  pluginProperties: AstNode[],
  seen: Set<AstNode>,
): boolean {
  if (seen.has(object)) {
    return true;
  }
  seen.add(object);
  if (!("properties" in object) || !Array.isArray(object.properties)) {
    return false;
  }
  for (const property of (object.properties as unknown[]).filter(isNode)) {
    if (property.type === "Property" && propertyName(property) === "plugins") {
      pluginProperties.push(property);
      continue;
    }
    if (property.type === "SpreadElement" && "argument" in property && isNode(property.argument)) {
      const spreadObject = resolveObjectExpression(property.argument, objects, reassigned);
      if (spreadObject === undefined) {
        return false;
      }
      if (!collectPluginPropertiesFromObject(spreadObject, objects, reassigned, pluginProperties, seen)) {
        return false;
      }
    }
  }
  return true;
}

export function stripServerPlugins(source: string): string {
  const program = parseAst(source, { astType: "js", lang: "tsx", range: true });
  const root = program as unknown as AstNode;
  const body = program.body as unknown as AstNode[];
  const imports = body.filter((node): node is ImportDeclaration => node.type === "ImportDeclaration");
  const renderNames = new Set<string>();
  const renderNamespaces = new Set<string>();
  for (const declaration of imports) {
    if (!renderImport(declaration.source.value)) {
      continue;
    }
    for (const specifier of declaration.specifiers) {
      if (specifier.type === "ImportDefaultSpecifier") {
        renderNames.add(specifier.local.name);
      } else if (specifier.type === "ImportNamespaceSpecifier") {
        renderNamespaces.add(specifier.local.name);
      } else if (importedName(specifier) === "render") {
        renderNames.add(specifier.local.name);
      }
    }
  }

  const reassignedRender = collectRenderAliases(root, renderNames, renderNamespaces);
  assertRenderBindingsAnalyzable(root, renderNames, renderNamespaces, reassignedRender);

  const { objects, reassigned } = collectObjectBindings(root);
  const pluginProperties: AstNode[] = [];
  const pluginIdentifiers = new Set<string>();
  walk(root, (node) => {
    if (node.type !== "CallExpression" || !("callee" in node) || !("arguments" in node)) {
      return;
    }
    const callee = node.callee;
    const args = node.arguments;
    if (!isNode(callee) || !isRenderCallee(callee, renderNames, renderNamespaces) || !Array.isArray(args)) {
      return;
    }
    if (!isNode(args[0])) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
    const optionsObject = resolveObjectExpression(args[0], objects, reassigned);
    if (optionsObject === undefined) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
    const callPlugins: AstNode[] = [];
    if (!collectPluginPropertiesFromObject(optionsObject, objects, reassigned, callPlugins, new Set())) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
    for (const property of callPlugins) {
      pluginProperties.push(property);
      if ("value" in property && isNode(property.value)) {
        for (const name of collectIdentifiers(property.value)) {
          pluginIdentifiers.add(name);
        }
      }
    }
  });

  if (pluginProperties.length === 0) {
    return source;
  }

  const usedOutsidePlugins = new Set<string>();
  walk(root, (node) => {
    if (node.type === "ImportDeclaration" || pluginProperties.includes(node)) {
      return false;
    }
    if (node.type === "Identifier" && "name" in node && typeof node.name === "string") {
      usedOutsidePlugins.add(node.name);
    }
  });

  const transformed = new MagicString(source);
  for (const property of pluginProperties) {
    const parent = findParentObject(root, property);
    if (parent !== undefined && "properties" in parent && Array.isArray(parent.properties)) {
      const properties = (parent.properties as unknown[]).filter(isNode);
      removeObjectProperty(transformed, properties, properties.indexOf(property));
    }
  }

  for (const declaration of imports) {
    if (renderImport(declaration.source.value)) {
      continue;
    }
    const retained = declaration.specifiers.filter(
      (specifier) => !pluginIdentifiers.has(specifier.local.name) || usedOutsidePlugins.has(specifier.local.name),
    );
    if (retained.length === declaration.specifiers.length) {
      continue;
    }
    if (retained.length === 0) {
      transformed.remove(declaration.start, declaration.end);
    } else {
      transformed.overwrite(declaration.start, declaration.end, formatImport(declaration.source.value, retained));
    }
  }
  return transformed.toString();
}

function findParentObject(root: AstNode, target: AstNode): AstNode | undefined {
  let parent: AstNode | undefined;
  walk(root, (node) => {
    if (parent !== undefined) {
      return false;
    }
    if ("properties" in node && Array.isArray(node.properties) && node.properties.includes(target)) {
      parent = node;
      return false;
    }
  });
  return parent;
}

export function normalizeNpmSpecifier(specifier: string): string | undefined {
  if (!specifier.startsWith("npm:")) {
    return undefined;
  }
  const value = specifier.slice(4);
  const match = value.startsWith("@")
    ? /^(@[^/]+\/[^/@]+)(?:@[^/]+)?(\/.*)?$/u.exec(value)
    : /^([^/@]+)(?:@[^/]+)?(\/.*)?$/u.exec(value);
  if (match === null) {
    throw new Error(`@belgie/render: invalid npm specifier ${specifier}`);
  }
  return `${match[1]}${match[2] ?? ""}`;
}

const CLIENT_API_SOURCE = [
  'const MARKER = Symbol.for("@belgie/render/client-definition");',
  "export function render(options) {",
  "  return Object.freeze({ [MARKER]: true, widget: options.widget });",
  "}",
  "export function assertRenderDefinition(value) {",
  '  if (value === null || typeof value !== "object" || value[MARKER] !== true) {',
  '    throw new TypeError("@belgie/render: run export must return render(...)");',
  "  }",
  "  return value;",
  "}",
  "",
].join("\n");

const CLIENT_ENTRY_SOURCE = [
  'import { StrictMode, createElement, isValidElement } from "react";',
  'import { createRoot } from "react-dom/client";',
  `import * as caller from ${JSON.stringify(CLIENT_SOURCE_ID)};`,
  `import { assertRenderDefinition } from ${JSON.stringify(CLIENT_RENDER_ID)};`,
  'const run = typeof caller.default === "function" ? caller.default : caller.run;',
  'if (typeof run !== "function") throw new TypeError("@belgie/render: caller must export a default function or named run function");',
  "const definition = assertRenderDefinition(await run());",
  'if (!isValidElement(definition.widget)) throw new TypeError("@belgie/render: widget must be a React element");',
  'const root = document.getElementById("root");',
  'if (root === null) throw new Error("@belgie/render: root element is missing");',
  "createRoot(root).render(createElement(StrictMode, null, definition.widget));",
  "",
].join("\n");

export function createInlineSourcePlugin(context: RenderContext): Plugin {
  return {
    name: "belgie-render-inline-source",
    enforce: "pre",
    async resolveId(id, importer) {
      if (id === CLIENT_ENTRY_ID) {
        return RESOLVED_CLIENT_ENTRY_ID;
      }
      if (id === CLIENT_SOURCE_ID) {
        return RESOLVED_CLIENT_SOURCE_ID;
      }
      if (id === CLIENT_RENDER_ID || renderImport(id)) {
        return RESOLVED_CLIENT_RENDER_ID;
      }
      if (id.startsWith("jsr:")) {
        throw new Error(`@belgie/render: retained browser import is not supported: ${id}`);
      }
      const normalized = normalizeNpmSpecifier(id);
      if (normalized !== undefined) {
        return this.resolve(normalized, importer, { skipSelf: true });
      }
      return null;
    },
    load(id) {
      if (id === RESOLVED_CLIENT_ENTRY_ID) {
        return CLIENT_ENTRY_SOURCE;
      }
      if (id === RESOLVED_CLIENT_SOURCE_ID) {
        return stripServerPlugins(context.source);
      }
      if (id === RESOLVED_CLIENT_RENDER_ID) {
        return CLIENT_API_SOURCE;
      }
      return null;
    },
  };
}
