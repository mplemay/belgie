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

type PropertyKeyClass = { kind: "static"; name: string } | { kind: "unknown" };

function classifyPropertyKey(node: AstNode): PropertyKeyClass {
  if (node.type !== "Property" || !("key" in node) || !isNode(node.key)) {
    return { kind: "unknown" };
  }
  const key = node.key;
  const computed = "computed" in node && node.computed;
  if (!computed) {
    if (key.type === "Identifier" && "name" in key && typeof key.name === "string") {
      return { kind: "static", name: key.name };
    }
    if (key.type === "Literal" && "value" in key && typeof key.value === "string") {
      return { kind: "static", name: key.value };
    }
    return { kind: "unknown" };
  }
  if (key.type === "Literal" && "value" in key && typeof key.value === "string") {
    return { kind: "static", name: key.value };
  }
  return { kind: "unknown" };
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

const UNANALYZABLE_WIDGET_ERROR =
  "@belgie/render: widget must be a statically analyzable render(...) options expression";

export const WIDGET_EXPORT_NAME = "__belgie_widget";

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

function collectOptionPropertiesFromObject(
  object: AstNode,
  objects: Map<string, AstNode>,
  reassigned: Set<string>,
  pluginProperties: AstNode[],
  widgetProperties: AstNode[],
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
    if (property.type === "Property") {
      const key = classifyPropertyKey(property);
      if (key.kind === "unknown") {
        return false;
      }
      if (key.name === "plugins") {
        pluginProperties.push(property);
      } else if (key.name === "widget") {
        widgetProperties.push(property);
      }
      continue;
    }
    if (property.type === "SpreadElement" && "argument" in property && isNode(property.argument)) {
      const spreadObject = resolveObjectExpression(property.argument, objects, reassigned);
      if (spreadObject === undefined) {
        return false;
      }
      if (
        !collectOptionPropertiesFromObject(spreadObject, objects, reassigned, pluginProperties, widgetProperties, seen)
      ) {
        return false;
      }
    }
  }
  return true;
}

interface SimpleDeclarator {
  declaration: AstNode;
  declarator: AstNode;
  init: AstNode;
  name: string;
}

function addBindingPatternNames(node: AstNode, into: Set<string>): void {
  if (node.type === "Identifier" && "name" in node && typeof node.name === "string") {
    into.add(node.name);
    return;
  }
  for (const name of collectIdentifiers(node)) {
    into.add(name);
  }
}

function collectExportedBindingNames(root: AstNode): Set<string> {
  const exported = new Set<string>();
  walk(root, (node) => {
    if (node.type === "ExportNamedDeclaration" && "specifiers" in node && Array.isArray(node.specifiers)) {
      for (const specifier of node.specifiers.filter(isNode)) {
        if ("local" in specifier && isNode(specifier.local)) {
          addBindingPatternNames(specifier.local, exported);
        }
      }
    }
    if (
      (node.type !== "ExportNamedDeclaration" && node.type !== "ExportDefaultDeclaration") ||
      !("declaration" in node) ||
      !isNode(node.declaration) ||
      node.declaration.type !== "VariableDeclaration" ||
      !("declarations" in node.declaration) ||
      !Array.isArray(node.declaration.declarations)
    ) {
      return;
    }
    for (const declarator of node.declaration.declarations.filter(isNode)) {
      if ("id" in declarator && isNode(declarator.id)) {
        addBindingPatternNames(declarator.id, exported);
      }
    }
  });
  return exported;
}

function collectSimpleDeclarators(root: AstNode): {
  declarators: Map<string, SimpleDeclarator>;
  nonSimpleBound: Set<string>;
  redeclared: Set<string>;
} {
  const declarators = new Map<string, SimpleDeclarator>();
  const nonSimpleBound = new Set<string>();
  const redeclared = new Set<string>();
  walk(root, (node) => {
    if (node.type !== "VariableDeclaration" || !("declarations" in node) || !Array.isArray(node.declarations)) {
      return;
    }
    for (const value of node.declarations) {
      if (!isNode(value) || !("id" in value) || !isNode(value.id)) {
        continue;
      }
      const init = "init" in value && isNode(value.init) ? value.init : undefined;
      if (
        value.id.type === "Identifier" &&
        "name" in value.id &&
        typeof value.id.name === "string" &&
        init !== undefined
      ) {
        const name = value.id.name;
        if (declarators.has(name) || nonSimpleBound.has(name)) {
          redeclared.add(name);
          declarators.delete(name);
        } else {
          declarators.set(name, {
            declaration: node,
            declarator: value,
            init,
            name,
          });
        }
        continue;
      }
      for (const name of collectIdentifiers(value.id)) {
        nonSimpleBound.add(name);
        declarators.delete(name);
      }
    }
  });
  return { declarators, nonSimpleBound, redeclared };
}

function collectPluginOnlyBindings(
  root: AstNode,
  pluginIdentifiers: Set<string>,
  pluginProperties: AstNode[],
  reassigned: Set<string>,
): SimpleDeclarator[] {
  const exported = collectExportedBindingNames(root);
  const { declarators, nonSimpleBound, redeclared } = collectSimpleDeclarators(root);
  const blocked = new Set([...reassigned, ...redeclared, ...exported]);
  const pluginOnly = new Map<string, SimpleDeclarator>();

  for (;;) {
    let discovered = false;
    for (const name of pluginIdentifiers) {
      if (pluginOnly.has(name)) {
        continue;
      }
      if (nonSimpleBound.has(name)) {
        throw new Error(UNANALYZABLE_PLUGINS_ERROR);
      }
      const binding = declarators.get(name);
      if (binding === undefined) {
        continue;
      }
      if (blocked.has(name)) {
        throw new Error(UNANALYZABLE_PLUGINS_ERROR);
      }
      pluginOnly.set(name, binding);
      for (const identifier of collectIdentifiers(binding.init)) {
        pluginIdentifiers.add(identifier);
      }
      discovered = true;
    }
    if (!discovered) {
      break;
    }
  }

  const skipped = new Set<AstNode>([
    ...pluginProperties,
    ...[...pluginOnly.values()].map((binding) => binding.declarator),
  ]);
  walk(root, (node) => {
    if (node.type === "ImportDeclaration" || skipped.has(node)) {
      return false;
    }
    if (node.type !== "Identifier" || !("name" in node) || typeof node.name !== "string") {
      return;
    }
    if (pluginOnly.has(node.name)) {
      throw new Error(UNANALYZABLE_PLUGINS_ERROR);
    }
  });

  return [...pluginOnly.values()];
}

function removeVariableDeclarators(transformed: MagicString, bindings: SimpleDeclarator[]): void {
  const byDeclaration = new Map<AstNode, SimpleDeclarator[]>();
  for (const binding of bindings) {
    const group = byDeclaration.get(binding.declaration);
    if (group === undefined) {
      byDeclaration.set(binding.declaration, [binding]);
    } else {
      group.push(binding);
    }
  }
  for (const [declaration, group] of byDeclaration) {
    if (!("declarations" in declaration) || !Array.isArray(declaration.declarations)) {
      continue;
    }
    const declarators = declaration.declarations.filter(isNode);
    if (group.length >= declarators.length) {
      transformed.remove(declaration.start, declaration.end);
      continue;
    }
    const removing = new Set(group.map((binding) => binding.declarator));
    for (let index = declarators.length - 1; index >= 0; index -= 1) {
      const declarator = declarators[index];
      if (declarator === undefined || !removing.has(declarator)) {
        continue;
      }
      if (index === 0) {
        const next = declarators.find((candidate, candidateIndex) => candidateIndex > 0 && !removing.has(candidate));
        if (next !== undefined) {
          transformed.remove(declarator.start, next.start);
        }
      } else {
        const previous = declarators[index - 1];
        if (previous !== undefined) {
          transformed.remove(previous.end, declarator.end);
        }
      }
    }
  }
}

interface RenderOptionsAnalysis {
  imports: ImportDeclaration[];
  pluginIdentifiers: Set<string>;
  pluginProperties: AstNode[];
  reassigned: Set<string>;
  root: AstNode;
  widgetProperties: AstNode[];
}

function analyzeRenderOptions(source: string): RenderOptionsAnalysis {
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
  const widgetProperties: AstNode[] = [];
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
    const callWidgets: AstNode[] = [];
    if (!collectOptionPropertiesFromObject(optionsObject, objects, reassigned, callPlugins, callWidgets, new Set())) {
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
    for (const property of callWidgets) {
      widgetProperties.push(property);
    }
  });

  return { imports, pluginIdentifiers, pluginProperties, reassigned, root, widgetProperties };
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

function stripPluginsFromSource(source: string, analysis: RenderOptionsAnalysis): string {
  const { imports, pluginIdentifiers, pluginProperties, reassigned, root } = analysis;
  if (pluginProperties.length === 0) {
    return source;
  }

  const pluginOnlyBindings = collectPluginOnlyBindings(root, pluginIdentifiers, pluginProperties, reassigned);
  const skippedNodes = new Set<AstNode>([
    ...pluginProperties,
    ...pluginOnlyBindings.map((binding) => binding.declarator),
  ]);

  const usedOutsidePlugins = new Set<string>();
  walk(root, (node) => {
    if (node.type === "ImportDeclaration" || skippedNodes.has(node)) {
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
  removeVariableDeclarators(transformed, pluginOnlyBindings);

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

export function stripServerPlugins(source: string): string {
  return stripPluginsFromSource(source, analyzeRenderOptions(source));
}

function addNamedBindings(node: AstNode, names: Set<string>): void {
  if ((node.type === "FunctionDeclaration" || node.type === "ClassDeclaration") && "id" in node && isNode(node.id)) {
    addBindingPatternNames(node.id, names);
    return;
  }
  if (node.type !== "VariableDeclaration" || !("declarations" in node) || !Array.isArray(node.declarations)) {
    return;
  }
  for (const declarator of node.declarations.filter(isNode)) {
    if ("id" in declarator && isNode(declarator.id)) {
      addBindingPatternNames(declarator.id, names);
    }
  }
}

function addModuleDeclarationBindings(node: AstNode, names: Set<string>): void {
  if (node.type === "ImportDeclaration" && "specifiers" in node && Array.isArray(node.specifiers)) {
    for (const specifier of node.specifiers.filter(isNode)) {
      if ("local" in specifier && isNode(specifier.local)) {
        addBindingPatternNames(specifier.local, names);
      }
    }
    return;
  }
  if (node.type === "ExportNamedDeclaration") {
    if ("declaration" in node && isNode(node.declaration)) {
      addNamedBindings(node.declaration, names);
    }
    return;
  }
  if (node.type === "ExportDefaultDeclaration" && "declaration" in node && isNode(node.declaration)) {
    addNamedBindings(node.declaration, names);
    return;
  }
  addNamedBindings(node, names);
}

function collectModuleBindingNames(root: AstNode): Set<string> {
  const names = new Set<string>();
  if (!("body" in root) || !Array.isArray(root.body)) {
    return names;
  }
  for (const node of root.body.filter(isNode)) {
    addModuleDeclarationBindings(node, names);
  }
  return names;
}

function isNonComputedPropertyName(node: AstNode, parent: AstNode | undefined): boolean {
  if (parent === undefined) {
    return false;
  }
  if (
    parent.type === "MemberExpression" &&
    "computed" in parent &&
    !parent.computed &&
    "property" in parent &&
    parent.property === node
  ) {
    return true;
  }
  if (
    parent.type === "Property" &&
    "computed" in parent &&
    !parent.computed &&
    "key" in parent &&
    parent.key === node
  ) {
    return true;
  }
  if (
    parent.type === "MethodDefinition" &&
    "computed" in parent &&
    !parent.computed &&
    "key" in parent &&
    parent.key === node
  ) {
    return true;
  }
  return false;
}

function isTypeScriptTypeNode(node: AstNode): boolean {
  return (
    typeof node.type === "string" &&
    node.type.startsWith("TS") &&
    node.type !== "TSAsExpression" &&
    node.type !== "TSSatisfiesExpression" &&
    node.type !== "TSTypeAssertion" &&
    node.type !== "TSNonNullExpression"
  );
}

function collectWidgetReferences(widgetValue: AstNode): Set<string> {
  const names = new Set<string>();
  const parents = new Map<AstNode, AstNode>();
  walk(widgetValue, (node) => {
    if (isTypeScriptTypeNode(node)) {
      return false;
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        for (const item of value) {
          if (isNode(item)) {
            parents.set(item, node);
          }
        }
      } else if (isNode(value)) {
        parents.set(value, node);
      }
    }
    if (node.type === "JSXIdentifier" && "name" in node && typeof node.name === "string" && /^[A-Z]/u.test(node.name)) {
      names.add(node.name);
      return;
    }
    if (node.type !== "Identifier" || !("name" in node) || typeof node.name !== "string") {
      return;
    }
    if (isNonComputedPropertyName(node, parents.get(node))) {
      return;
    }
    names.add(node.name);
  });
  return names;
}

function resolveWidgetExpression(source: string, analysis: RenderOptionsAnalysis): AstNode {
  const { root, widgetProperties } = analysis;
  if (widgetProperties.length === 0) {
    throw new Error(UNANALYZABLE_WIDGET_ERROR);
  }
  const expressions: AstNode[] = [];
  for (const property of widgetProperties) {
    if (!("value" in property) || !isNode(property.value)) {
      throw new Error(UNANALYZABLE_WIDGET_ERROR);
    }
    expressions.push(property.value);
  }
  const texts = new Set(expressions.map((expression) => source.slice(expression.start, expression.end)));
  if (texts.size !== 1) {
    throw new Error(UNANALYZABLE_WIDGET_ERROR);
  }
  const widgetValue = expressions[0];
  if (widgetValue === undefined) {
    throw new Error(UNANALYZABLE_WIDGET_ERROR);
  }

  const moduleBindings = collectModuleBindingNames(root);
  if (moduleBindings.has(WIDGET_EXPORT_NAME)) {
    throw new Error(UNANALYZABLE_WIDGET_ERROR);
  }
  for (const name of collectWidgetReferences(widgetValue)) {
    if (!moduleBindings.has(name)) {
      throw new Error(UNANALYZABLE_WIDGET_ERROR);
    }
  }
  return widgetValue;
}

export function prepareBrowserCaller(source: string): string {
  const analysis = analyzeRenderOptions(source);
  const widgetValue = resolveWidgetExpression(source, analysis);
  const stripped = stripPluginsFromSource(source, analysis);
  const widgetSource = source.slice(widgetValue.start, widgetValue.end);
  return `${stripped}\nexport const ${WIDGET_EXPORT_NAME} = ${widgetSource};\n`;
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
  "export function render() {",
  '  throw new TypeError("@belgie/render: render cannot be called from the browser module graph");',
  "}",
  "",
].join("\n");

const CLIENT_ENTRY_SOURCE = [
  'import { StrictMode, createElement, isValidElement } from "react";',
  'import { createRoot } from "react-dom/client";',
  `import { ${WIDGET_EXPORT_NAME} as widget } from ${JSON.stringify(CLIENT_SOURCE_ID)};`,
  'if (!isValidElement(widget)) throw new TypeError("@belgie/render: widget must be a React element");',
  'const root = document.getElementById("root");',
  'if (root === null) throw new Error("@belgie/render: root element is missing");',
  "createRoot(root).render(createElement(StrictMode, null, widget));",
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
        return prepareBrowserCaller(context.source);
      }
      if (id === RESOLVED_CLIENT_RENDER_ID) {
        return CLIENT_API_SOURCE;
      }
      return null;
    },
  };
}
