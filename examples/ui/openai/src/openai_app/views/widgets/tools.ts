import { createGeneratedTool } from "@belgie/mcp/internal";

export type ChoosePartInput = Record<string, never>;

export interface ChoosePartOutput {
  action: string;
  part?: ChoosePartOutputPartView;
}

export interface ChoosePartOutputPartView {
  description: string;
  id: string;
  length: string;
  name: string;
  thumbnail?: string;
  uri: string;
}

export type PartsLibraryInput = Record<string, never>;

export interface PartsLibraryOutput {
  parts: readonly PartsLibraryOutputPartView[];
  units: string;
}

export interface PartsLibraryOutputPartView {
  description: string;
  id: string;
  length: string;
  name: string;
  thumbnail?: string;
  uri: string;
}

export interface SearchMentionsInput {
  query: string;
}

export interface SearchMentionsOutput {
  items: readonly (SearchMentionsOutputResourceLink | SearchMentionsOutputOpenAIMentionResource)[];
}

export interface SearchMentionsOutputAnnotations {
  audience?: readonly ("user" | "assistant")[] | null;
  lastModified?: string | null;
  priority?: number | null;
}

export interface SearchMentionsOutputIcon {
  mimeType?: string | null;
  sizes?: readonly string[] | null;
  src: string;
  theme?: "light" | "dark" | null;
}

export interface SearchMentionsOutputOpenAIMentionResource {
  icons?: readonly SearchMentionsOutputIcon[] | null;
  resourceUri: string;
  subtitle?: string | null;
  title: string;
  type?: "resource";
}

export interface SearchMentionsOutputResourceLink {
  _meta?: Record<string, unknown> | null;
  annotations?: SearchMentionsOutputAnnotations | null;
  description?: string | null;
  icons?: readonly SearchMentionsOutputIcon[] | null;
  mimeType?: string | null;
  name: string;
  size?: number | null;
  title?: string | null;
  type?: "resource_link";
  uri: string;
}

export type SettingsReadInput = Record<string, never>;

export interface SettingsReadOutput {
  layout?: readonly SettingsReadOutputOpenAISettingsGroup[] | null;
  schema: Record<string, SettingsReadOutputJsonValue>;
  values: SettingsReadOutputPreferences;
}

export type SettingsReadOutputJsonValue = unknown;

export interface SettingsReadOutputOpenAISettingsGroup {
  items: readonly (SettingsReadOutputOpenAISettingsProperty | SettingsReadOutputOpenAISettingsTool)[];
  kind?: "group";
  title: string;
}

export interface SettingsReadOutputOpenAISettingsProperty {
  kind?: "property";
  property: string;
}

export interface SettingsReadOutputOpenAISettingsTool {
  description?: string | null;
  kind?: "tool";
  title: string;
  tool: string;
}

export interface SettingsReadOutputPreferences {
  showThumbnails: boolean;
  units: "mm" | "in";
}

export interface SettingsUpdateInput {
  set: SettingsUpdateInputSettingsPatch;
}

export interface SettingsUpdateInputSettingsPatch {
  showThumbnails?: boolean;
  units?: "mm" | "in";
}

export interface SettingsUpdateOutput {
  values: SettingsUpdateOutputPreferences;
}

export interface SettingsUpdateOutputPreferences {
  showThumbnails: boolean;
  units: "mm" | "in";
}

export interface StlViewerInput {
  file?: StlViewerInputFileInput | null;
}

export interface StlViewerInputFileInput {
  name: string;
  resourceUri: string;
}

export interface StlViewerOutput {
  file: StlViewerOutputFileInput | null;
  path: string | null;
}

export interface StlViewerOutputFileInput {
  name: string;
  resourceUri: string;
}

/** Ask the user to pick a part from thumbnails. */
export const choosePart = createGeneratedTool<ChoosePartInput, ChoosePartOutput>("choose-part", {
  $defs: {
    PartView: {
      properties: {
        description: {
          title: "Description",
          type: "string",
        },
        id: {
          title: "Id",
          type: "string",
        },
        length: {
          title: "Length",
          type: "string",
        },
        name: {
          title: "Name",
          type: "string",
        },
        thumbnail: {
          title: "Thumbnail",
          type: "string",
        },
        uri: {
          title: "Uri",
          type: "string",
        },
      },
      required: ["id", "name", "description", "length", "uri"],
      title: "PartView",
      type: "object",
    },
  },
  properties: {
    action: {
      title: "Action",
      type: "string",
    },
    part: {
      $ref: "#/$defs/PartView",
    },
  },
  required: ["action"],
  title: "ChosenPart",
  type: "object",
});

/** Browse the CAD parts library. */
export const partsLibrary = createGeneratedTool<PartsLibraryInput, PartsLibraryOutput>("parts-library", {
  $defs: {
    PartView: {
      properties: {
        description: {
          title: "Description",
          type: "string",
        },
        id: {
          title: "Id",
          type: "string",
        },
        length: {
          title: "Length",
          type: "string",
        },
        name: {
          title: "Name",
          type: "string",
        },
        thumbnail: {
          title: "Thumbnail",
          type: "string",
        },
        uri: {
          title: "Uri",
          type: "string",
        },
      },
      required: ["id", "name", "description", "length", "uri"],
      title: "PartView",
      type: "object",
    },
  },
  properties: {
    parts: {
      items: {
        $ref: "#/$defs/PartView",
      },
      title: "Parts",
      type: "array",
    },
    units: {
      title: "Units",
      type: "string",
    },
  },
  required: ["parts", "units"],
  title: "LibraryResult",
  type: "object",
});

export const searchMentions = createGeneratedTool<SearchMentionsInput, SearchMentionsOutput>("search_mentions", {
  $defs: {
    Annotations: {
      description: "Optional annotations the client can use to inform how objects are used or displayed.",
      properties: {
        audience: {
          anyOf: [
            {
              items: {
                enum: ["user", "assistant"],
                type: "string",
              },
              type: "array",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Audience",
        },
        lastModified: {
          anyOf: [
            {
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Lastmodified",
        },
        priority: {
          anyOf: [
            {
              maximum: 1,
              minimum: 0,
              type: "number",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Priority",
        },
      },
      title: "Annotations",
      type: "object",
    },
    Icon: {
      description: "An optionally-sized icon for display in a user interface (2025-11-25+).",
      properties: {
        mimeType: {
          anyOf: [
            {
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Mimetype",
        },
        sizes: {
          anyOf: [
            {
              items: {
                type: "string",
              },
              type: "array",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Sizes",
        },
        src: {
          title: "Src",
          type: "string",
        },
        theme: {
          anyOf: [
            {
              enum: ["light", "dark"],
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Theme",
        },
      },
      required: ["src"],
      title: "Icon",
      type: "object",
    },
    OpenAIMentionResource: {
      additionalProperties: false,
      description: "One selectable MCP resource returned by mention search.",
      properties: {
        icons: {
          anyOf: [
            {
              items: {
                $ref: "#/$defs/Icon",
              },
              type: "array",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Icons",
        },
        resourceUri: {
          pattern: "\\S",
          title: "Resourceuri",
          type: "string",
        },
        subtitle: {
          anyOf: [
            {
              pattern: "\\S",
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Subtitle",
        },
        title: {
          pattern: "\\S",
          title: "Title",
          type: "string",
        },
        type: {
          const: "resource",
          default: "resource",
          title: "Type",
          type: "string",
        },
      },
      required: ["resourceUri", "title"],
      title: "OpenAIMentionResource",
      type: "object",
    },
    ResourceLink: {
      description:
        "A resource that the server is capable of reading, included in a prompt or tool call result.\n\nNote: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.",
      properties: {
        _meta: {
          anyOf: [
            {
              additionalProperties: true,
              type: "object",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Meta",
        },
        annotations: {
          anyOf: [
            {
              $ref: "#/$defs/Annotations",
            },
            {
              type: "null",
            },
          ],
          default: null,
        },
        description: {
          anyOf: [
            {
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Description",
        },
        icons: {
          anyOf: [
            {
              items: {
                $ref: "#/$defs/Icon",
              },
              type: "array",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Icons",
        },
        mimeType: {
          anyOf: [
            {
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Mimetype",
        },
        name: {
          title: "Name",
          type: "string",
        },
        size: {
          anyOf: [
            {
              type: "integer",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Size",
        },
        title: {
          anyOf: [
            {
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Title",
        },
        type: {
          const: "resource_link",
          default: "resource_link",
          title: "Type",
          type: "string",
        },
        uri: {
          title: "Uri",
          type: "string",
        },
      },
      required: ["name", "uri"],
      title: "ResourceLink",
      type: "object",
    },
  },
  additionalProperties: false,
  description: "Selectable resources returned by mention search.",
  properties: {
    items: {
      items: {
        discriminator: {
          mapping: {
            resource: "#/$defs/OpenAIMentionResource",
            resource_link: "#/$defs/ResourceLink",
          },
          propertyName: "type",
        },
        oneOf: [
          {
            $ref: "#/$defs/ResourceLink",
          },
          {
            $ref: "#/$defs/OpenAIMentionResource",
          },
        ],
      },
      title: "Items",
      type: "array",
    },
  },
  required: ["items"],
  title: "OpenAIMentionSearchResult",
  type: "object",
});

export const settingsRead = createGeneratedTool<SettingsReadInput, SettingsReadOutput>("settings.read", {
  $defs: {
    JsonValue: {},
    OpenAISettingsGroup: {
      additionalProperties: false,
      description: "An ordered section of settings and buttons. Groups cannot contain groups.",
      properties: {
        items: {
          items: {
            discriminator: {
              mapping: {
                property: "#/$defs/OpenAISettingsProperty",
                tool: "#/$defs/OpenAISettingsTool",
              },
              propertyName: "kind",
            },
            oneOf: [
              {
                $ref: "#/$defs/OpenAISettingsProperty",
              },
              {
                $ref: "#/$defs/OpenAISettingsTool",
              },
            ],
          },
          title: "Items",
          type: "array",
        },
        kind: {
          const: "group",
          default: "group",
          title: "Kind",
          type: "string",
        },
        title: {
          pattern: "\\S",
          title: "Title",
          type: "string",
        },
      },
      required: ["title", "items"],
      title: "OpenAISettingsGroup",
      type: "object",
    },
    OpenAISettingsProperty: {
      additionalProperties: false,
      description: "Reference a schema property by its wire key, including any Pydantic alias.",
      properties: {
        kind: {
          const: "property",
          default: "property",
          title: "Kind",
          type: "string",
        },
        property: {
          title: "Property",
          type: "string",
        },
      },
      required: ["property"],
      title: "OpenAISettingsProperty",
      type: "object",
    },
    OpenAISettingsTool: {
      additionalProperties: false,
      description: "A layout button invoking a same-server tool accepting an empty object.",
      properties: {
        description: {
          anyOf: [
            {
              type: "string",
            },
            {
              type: "null",
            },
          ],
          default: null,
          title: "Description",
        },
        kind: {
          const: "tool",
          default: "tool",
          title: "Kind",
          type: "string",
        },
        title: {
          pattern: "\\S",
          title: "Title",
          type: "string",
        },
        tool: {
          pattern: "\\S",
          title: "Tool",
          type: "string",
        },
      },
      required: ["tool", "title"],
      title: "OpenAISettingsTool",
      type: "object",
    },
    Preferences: {
      properties: {
        showThumbnails: {
          title: "Show thumbnails",
          type: "boolean",
        },
        units: {
          enum: ["mm", "in"],
          title: "Measurement units",
          type: "string",
        },
      },
      required: ["units", "showThumbnails"],
      title: "Preferences",
      type: "object",
    },
  },
  additionalProperties: false,
  properties: {
    layout: {
      anyOf: [
        {
          items: {
            $ref: "#/$defs/OpenAISettingsGroup",
          },
          type: "array",
        },
        {
          type: "null",
        },
      ],
      default: null,
      title: "Layout",
    },
    schema: {
      additionalProperties: {
        $ref: "#/$defs/JsonValue",
      },
      title: "Schema",
      type: "object",
    },
    values: {
      $ref: "#/$defs/Preferences",
    },
  },
  required: ["schema", "values"],
  title: "SettingsReadResult",
  type: "object",
});

export const settingsUpdate = createGeneratedTool<SettingsUpdateInput, SettingsUpdateOutput>("settings.update", {
  $defs: {
    Preferences: {
      properties: {
        showThumbnails: {
          title: "Show thumbnails",
          type: "boolean",
        },
        units: {
          enum: ["mm", "in"],
          title: "Measurement units",
          type: "string",
        },
      },
      required: ["units", "showThumbnails"],
      title: "Preferences",
      type: "object",
    },
  },
  additionalProperties: false,
  properties: {
    values: {
      $ref: "#/$defs/Preferences",
    },
  },
  required: ["values"],
  title: "SettingsUpdateResult",
  type: "object",
});

/** View and edit an STL file. */
export const stlViewer = createGeneratedTool<StlViewerInput, StlViewerOutput>("stl-viewer", {
  $defs: {
    FileInput: {
      properties: {
        name: {
          title: "Name",
          type: "string",
        },
        resourceUri: {
          title: "Resourceuri",
          type: "string",
        },
      },
      required: ["name", "resourceUri"],
      title: "FileInput",
      type: "object",
    },
  },
  properties: {
    file: {
      anyOf: [
        {
          $ref: "#/$defs/FileInput",
        },
        {
          type: "null",
        },
      ],
    },
    path: {
      anyOf: [
        {
          type: "string",
        },
        {
          type: "null",
        },
      ],
      title: "Path",
    },
  },
  required: ["file", "path"],
  title: "ViewerResult",
  type: "object",
});
