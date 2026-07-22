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

export function stripServerPlugins(source: string): string {
  const program = parseAst(source, { astType: "js", lang: "tsx", range: true });
  const body = program.body as unknown as AstNode[];
  const imports = body.filter((node): node is ImportDeclaration => node.type === "ImportDeclaration");
  const renderNames = new Set<string>();
  for (const declaration of imports) {
    if (!renderImport(declaration.source.value)) {
      continue;
    }
    for (const specifier of declaration.specifiers) {
      if (specifier.type === "ImportDefaultSpecifier") {
        renderNames.add(specifier.local.name);
      } else if (importedName(specifier) === "render") {
        renderNames.add(specifier.local.name);
      }
    }
  }

  const pluginProperties: AstNode[] = [];
  const pluginIdentifiers = new Set<string>();
  walk(program as unknown as AstNode, (node) => {
    if (node.type !== "CallExpression" || !("callee" in node) || !("arguments" in node)) {
      return;
    }
    const callee = node.callee;
    const args = node.arguments;
    if (
      !isNode(callee) ||
      callee.type !== "Identifier" ||
      !("name" in callee) ||
      typeof callee.name !== "string" ||
      !renderNames.has(callee.name) ||
      !Array.isArray(args) ||
      !isNode(args[0]) ||
      args[0].type !== "ObjectExpression" ||
      !("properties" in args[0]) ||
      !Array.isArray(args[0].properties)
    ) {
      return;
    }
    const properties = (args[0].properties as unknown[]).filter(isNode);
    const propertyIndex = properties.findIndex(
      (property) => property.type === "Property" && propertyName(property) === "plugins",
    );
    if (propertyIndex === -1) {
      return;
    }
    const property = properties[propertyIndex];
    if (property === undefined) {
      return;
    }
    pluginProperties.push(property);
    if ("value" in property && isNode(property.value)) {
      for (const name of collectIdentifiers(property.value)) {
        pluginIdentifiers.add(name);
      }
    }
  });

  if (pluginProperties.length === 0) {
    return source;
  }

  const usedOutsidePlugins = new Set<string>();
  walk(program as unknown as AstNode, (node) => {
    if (node.type === "ImportDeclaration" || pluginProperties.includes(node)) {
      return false;
    }
    if (node.type === "Identifier" && "name" in node && typeof node.name === "string") {
      usedOutsidePlugins.add(node.name);
    }
  });

  const transformed = new MagicString(source);
  for (const property of pluginProperties) {
    const parent = findParentObject(program as unknown as AstNode, property);
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
