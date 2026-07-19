import type { RawToolResult } from "@belgie/mcp";
import { createGeneratedRawTool, createGeneratedTool } from "@belgie/mcp/internal";

export type AnnotatedClassOutputInput = Record<string, never>;

export type AnnotatedClassOutputOutput = {
  "x": number;
  "y": number;
};

export type AnyOutputInput = Record<string, never>;

export type AnyOutputOutput = RawToolResult;

export type AudioHelperInput = Record<string, never>;

export type AudioHelperOutput = RawToolResult;

export type CommonInputsInput = {
  "amount": number | string;
  "anything": Record<string, unknown>;
  "choice": ("a" | "b") & string;
  "clock": string;
  "color": CommonInputsInputColor;
  "constrained": number;
  "count": number;
  "day": string;
  "delta": string;
  "enabled": boolean;
  "frozen": readonly number[];
  "items": readonly string[];
  "json_value": CommonInputsInputJsonValue;
  "limit"?: number;
  "mapping": Record<string, number>;
  "node": CommonInputsInputNode;
  "optional"?: string | null;
  "pair": readonly [string, number];
  "path": string;
  "payload": CommonInputsInputPayload;
  "point": CommonInputsInputPoint;
  "ratio": number | null;
  "raw": string;
  "required": string;
  "tags": readonly string[];
  "uid": string;
  "url": string;
  "variable": readonly number[];
  "when": string;
  "zoo": CommonInputsInputZoo;
};

export type CommonInputsInputCat = {
  "kind": "cat" & string;
  "lives": number;
};

export type CommonInputsInputColor = ("red" | "blue") & string;

export type CommonInputsInputDog = {
  "good": boolean;
  "kind": "dog" & string;
};

export type CommonInputsInputJsonValue = unknown;

export type CommonInputsInputNode = {
  "child"?: CommonInputsInputNode | null;
  "name": string;
};

export type CommonInputsInputPayload = {
  "count"?: number;
  "name": string;
};

export type CommonInputsInputPoint = {
  "x": number;
  "y": number;
};

export type CommonInputsInputZoo = {
  "pet": CommonInputsInputCat | CommonInputsInputDog;
};

export type CommonInputsOutput = {
  "node": CommonInputsOutputNode;
  "payload": CommonInputsOutputPayload;
  "point": CommonInputsOutputPoint;
  "standard": CommonInputsOutputStandardValues;
  "zoo": CommonInputsOutputZoo;
};

export type CommonInputsOutputCat = {
  "kind": "cat" & string;
  "lives": number;
};

export type CommonInputsOutputDog = {
  "good": boolean;
  "kind": "dog" & string;
};

export type CommonInputsOutputNode = {
  "child"?: CommonInputsOutputNode | null;
  "name": string;
};

export type CommonInputsOutputPayload = {
  "count"?: number;
  "name": string;
};

export type CommonInputsOutputPoint = {
  "x": number;
  "y": number;
};

export type CommonInputsOutputStandardValues = {
  "amount": number | string;
  "clock": string;
  "day": string;
  "delta": string;
  "path": string;
  "uid": string;
  "url": string;
  "when": string;
};

export type CommonInputsOutputZoo = {
  "pet": CommonInputsOutputCat | CommonInputsOutputDog;
};

export type ContentBlocksInput = Record<string, never>;

export type ContentBlocksOutput = {
  "result": readonly (ContentBlocksOutputTextContent | ContentBlocksOutputImageContent | ContentBlocksOutputAudioContent | ContentBlocksOutputResourceLink | ContentBlocksOutputEmbeddedResource)[];
};

export type ContentBlocksOutputAnnotations = {
  "audience"?: readonly (("user" | "assistant") & string)[] | null;
  "lastModified"?: string | null;
  "priority"?: number | null;
};

export type ContentBlocksOutputAudioContent = {
  "_meta"?: Record<string, unknown> | null;
  "annotations"?: ContentBlocksOutputAnnotations | null;
  "data": string;
  "mimeType": string;
  "type"?: "audio" & string;
};

export type ContentBlocksOutputBlobResourceContents = {
  "_meta"?: Record<string, unknown> | null;
  "blob": string;
  "mimeType"?: string | null;
  "uri": string;
};

export type ContentBlocksOutputEmbeddedResource = {
  "_meta"?: Record<string, unknown> | null;
  "annotations"?: ContentBlocksOutputAnnotations | null;
  "resource": ContentBlocksOutputTextResourceContents | ContentBlocksOutputBlobResourceContents;
  "type"?: "resource" & string;
};

export type ContentBlocksOutputIcon = {
  "mimeType"?: string | null;
  "sizes"?: readonly string[] | null;
  "src": string;
  "theme"?: (("light" | "dark") & string) | null;
};

export type ContentBlocksOutputImageContent = {
  "_meta"?: Record<string, unknown> | null;
  "annotations"?: ContentBlocksOutputAnnotations | null;
  "data": string;
  "mimeType": string;
  "type"?: "image" & string;
};

export type ContentBlocksOutputResourceLink = {
  "_meta"?: Record<string, unknown> | null;
  "annotations"?: ContentBlocksOutputAnnotations | null;
  "description"?: string | null;
  "icons"?: readonly ContentBlocksOutputIcon[] | null;
  "mimeType"?: string | null;
  "name": string;
  "size"?: number | null;
  "title"?: string | null;
  "type"?: "resource_link" & string;
  "uri": string;
};

export type ContentBlocksOutputTextContent = {
  "_meta"?: Record<string, unknown> | null;
  "annotations"?: ContentBlocksOutputAnnotations | null;
  "text": string;
  "type"?: "text" & string;
};

export type ContentBlocksOutputTextResourceContents = {
  "_meta"?: Record<string, unknown> | null;
  "mimeType"?: string | null;
  "text": string;
  "uri": string;
};

export type DataclassOutputInput = Record<string, never>;

export type DataclassOutputOutput = {
  "x": number;
  "y": number;
};

export type DictionaryOutputInput = Record<string, never>;

export type DictionaryOutputOutput = Record<string, number>;

export type DirectResultInput = Record<string, never>;

export type DirectResultOutput = RawToolResult;

export type DisabledOutputInput = Record<string, never>;

export type DisabledOutputOutput = RawToolResult;

export type GenericOutputInput = Record<string, never>;

export type GenericOutputOutput = {
  "result": readonly string[];
};

export type ImageHelperInput = Record<string, never>;

export type ImageHelperOutput = RawToolResult;

export type PrimitiveOutputInput = Record<string, never>;

export type PrimitiveOutputOutput = {
  "result": string;
};

export type TypedDictOutputInput = Record<string, never>;

export type TypedDictOutputOutput = {
  "count": number;
  "name": string;
};

export const annotatedClassOutput = createGeneratedTool<AnnotatedClassOutputInput, AnnotatedClassOutputOutput>(
  "annotated-class-output",
  {
    "properties": {
      "x": {
        "title": "X",
        "type": "number"
      },
      "y": {
        "title": "Y",
        "type": "number"
      }
    },
    "required": [
      "x",
      "y"
    ],
    "title": "AnnotatedPoint",
    "type": "object"
  }
);

export const anyOutput = createGeneratedRawTool<AnyOutputInput>(
  "any-output",
);

export const audioHelper = createGeneratedRawTool<AudioHelperInput>(
  "audio-helper",
);

export const commonInputs = createGeneratedTool<CommonInputsInput, CommonInputsOutput>(
  "common-inputs",
  {
    "$defs": {
      "Cat": {
        "properties": {
          "kind": {
            "const": "cat",
            "title": "Kind",
            "type": "string"
          },
          "lives": {
            "title": "Lives",
            "type": "integer"
          }
        },
        "required": [
          "kind",
          "lives"
        ],
        "title": "Cat",
        "type": "object"
      },
      "Dog": {
        "properties": {
          "good": {
            "title": "Good",
            "type": "boolean"
          },
          "kind": {
            "const": "dog",
            "title": "Kind",
            "type": "string"
          }
        },
        "required": [
          "kind",
          "good"
        ],
        "title": "Dog",
        "type": "object"
      },
      "Node": {
        "properties": {
          "child": {
            "anyOf": [
              {
                "$ref": "#/$defs/Node"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "name": {
            "title": "Name",
            "type": "string"
          }
        },
        "required": [
          "name"
        ],
        "title": "Node",
        "type": "object"
      },
      "Payload": {
        "properties": {
          "count": {
            "title": "Count",
            "type": "integer"
          },
          "name": {
            "title": "Name",
            "type": "string"
          }
        },
        "required": [
          "name"
        ],
        "title": "Payload",
        "type": "object"
      },
      "Point": {
        "properties": {
          "x": {
            "title": "X",
            "type": "number"
          },
          "y": {
            "title": "Y",
            "type": "number"
          }
        },
        "required": [
          "x",
          "y"
        ],
        "title": "Point",
        "type": "object"
      },
      "StandardValues": {
        "properties": {
          "amount": {
            "anyOf": [
              {
                "type": "number"
              },
              {
                "pattern": "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$",
                "type": "string"
              }
            ],
            "title": "Amount"
          },
          "clock": {
            "format": "time",
            "title": "Clock",
            "type": "string"
          },
          "day": {
            "format": "date",
            "title": "Day",
            "type": "string"
          },
          "delta": {
            "format": "duration",
            "title": "Delta",
            "type": "string"
          },
          "path": {
            "format": "path",
            "title": "Path",
            "type": "string"
          },
          "uid": {
            "format": "uuid",
            "title": "Uid",
            "type": "string"
          },
          "url": {
            "format": "uri",
            "minLength": 1,
            "title": "Url",
            "type": "string"
          },
          "when": {
            "format": "date-time",
            "title": "When",
            "type": "string"
          }
        },
        "required": [
          "when",
          "day",
          "clock",
          "delta",
          "amount",
          "uid",
          "path",
          "url"
        ],
        "title": "StandardValues",
        "type": "object"
      },
      "Zoo": {
        "properties": {
          "pet": {
            "discriminator": {
              "mapping": {
                "cat": "#/$defs/Cat",
                "dog": "#/$defs/Dog"
              },
              "propertyName": "kind"
            },
            "oneOf": [
              {
                "$ref": "#/$defs/Cat"
              },
              {
                "$ref": "#/$defs/Dog"
              }
            ],
            "title": "Pet"
          }
        },
        "required": [
          "pet"
        ],
        "title": "Zoo",
        "type": "object"
      }
    },
    "properties": {
      "node": {
        "$ref": "#/$defs/Node"
      },
      "payload": {
        "$ref": "#/$defs/Payload"
      },
      "point": {
        "$ref": "#/$defs/Point"
      },
      "standard": {
        "$ref": "#/$defs/StandardValues"
      },
      "zoo": {
        "$ref": "#/$defs/Zoo"
      }
    },
    "required": [
      "payload",
      "point",
      "node",
      "zoo",
      "standard"
    ],
    "title": "CommonOutput",
    "type": "object"
  }
);

export const contentBlocks = createGeneratedTool<ContentBlocksInput, ContentBlocksOutput>(
  "content-blocks",
  {
    "$defs": {
      "Annotations": {
        "description": "Optional annotations the client can use to inform how objects are used or displayed.",
        "properties": {
          "audience": {
            "anyOf": [
              {
                "items": {
                  "enum": [
                    "user",
                    "assistant"
                  ],
                  "type": "string"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Audience"
          },
          "lastModified": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Lastmodified"
          },
          "priority": {
            "anyOf": [
              {
                "maximum": 1,
                "minimum": 0,
                "type": "number"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Priority"
          }
        },
        "title": "Annotations",
        "type": "object"
      },
      "AudioContent": {
        "description": "Audio provided to or from an LLM.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "annotations": {
            "anyOf": [
              {
                "$ref": "#/$defs/Annotations"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "data": {
            "title": "Data",
            "type": "string"
          },
          "mimeType": {
            "title": "Mimetype",
            "type": "string"
          },
          "type": {
            "const": "audio",
            "default": "audio",
            "title": "Type",
            "type": "string"
          }
        },
        "required": [
          "data",
          "mimeType"
        ],
        "title": "AudioContent",
        "type": "object"
      },
      "BlobResourceContents": {
        "description": "Binary contents of a resource.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "blob": {
            "title": "Blob",
            "type": "string"
          },
          "mimeType": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Mimetype"
          },
          "uri": {
            "title": "Uri",
            "type": "string"
          }
        },
        "required": [
          "uri",
          "blob"
        ],
        "title": "BlobResourceContents",
        "type": "object"
      },
      "EmbeddedResource": {
        "description": "The contents of a resource, embedded into a prompt or tool call result.\n\nIt is up to the client how best to render embedded resources for the benefit\nof the LLM and/or the user.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "annotations": {
            "anyOf": [
              {
                "$ref": "#/$defs/Annotations"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "resource": {
            "anyOf": [
              {
                "$ref": "#/$defs/TextResourceContents"
              },
              {
                "$ref": "#/$defs/BlobResourceContents"
              }
            ],
            "title": "Resource"
          },
          "type": {
            "const": "resource",
            "default": "resource",
            "title": "Type",
            "type": "string"
          }
        },
        "required": [
          "resource"
        ],
        "title": "EmbeddedResource",
        "type": "object"
      },
      "Icon": {
        "description": "An optionally-sized icon for display in a user interface (2025-11-25+).",
        "properties": {
          "mimeType": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Mimetype"
          },
          "sizes": {
            "anyOf": [
              {
                "items": {
                  "type": "string"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Sizes"
          },
          "src": {
            "title": "Src",
            "type": "string"
          },
          "theme": {
            "anyOf": [
              {
                "enum": [
                  "light",
                  "dark"
                ],
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Theme"
          }
        },
        "required": [
          "src"
        ],
        "title": "Icon",
        "type": "object"
      },
      "ImageContent": {
        "description": "An image provided to or from an LLM.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "annotations": {
            "anyOf": [
              {
                "$ref": "#/$defs/Annotations"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "data": {
            "title": "Data",
            "type": "string"
          },
          "mimeType": {
            "title": "Mimetype",
            "type": "string"
          },
          "type": {
            "const": "image",
            "default": "image",
            "title": "Type",
            "type": "string"
          }
        },
        "required": [
          "data",
          "mimeType"
        ],
        "title": "ImageContent",
        "type": "object"
      },
      "ResourceLink": {
        "description": "A resource that the server is capable of reading, included in a prompt or tool call result.\n\nNote: resource links returned by tools are not guaranteed to appear in the results of `resources/list` requests.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "annotations": {
            "anyOf": [
              {
                "$ref": "#/$defs/Annotations"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "description": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Description"
          },
          "icons": {
            "anyOf": [
              {
                "items": {
                  "$ref": "#/$defs/Icon"
                },
                "type": "array"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Icons"
          },
          "mimeType": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Mimetype"
          },
          "name": {
            "title": "Name",
            "type": "string"
          },
          "size": {
            "anyOf": [
              {
                "type": "integer"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Size"
          },
          "title": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Title"
          },
          "type": {
            "const": "resource_link",
            "default": "resource_link",
            "title": "Type",
            "type": "string"
          },
          "uri": {
            "title": "Uri",
            "type": "string"
          }
        },
        "required": [
          "name",
          "uri"
        ],
        "title": "ResourceLink",
        "type": "object"
      },
      "TextContent": {
        "description": "Text provided to or from an LLM.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "annotations": {
            "anyOf": [
              {
                "$ref": "#/$defs/Annotations"
              },
              {
                "type": "null"
              }
            ],
            "default": null
          },
          "text": {
            "title": "Text",
            "type": "string"
          },
          "type": {
            "const": "text",
            "default": "text",
            "title": "Type",
            "type": "string"
          }
        },
        "required": [
          "text"
        ],
        "title": "TextContent",
        "type": "object"
      },
      "TextResourceContents": {
        "description": "Text contents of a resource.",
        "properties": {
          "_meta": {
            "anyOf": [
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Meta"
          },
          "mimeType": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "type": "null"
              }
            ],
            "default": null,
            "title": "Mimetype"
          },
          "text": {
            "title": "Text",
            "type": "string"
          },
          "uri": {
            "title": "Uri",
            "type": "string"
          }
        },
        "required": [
          "uri",
          "text"
        ],
        "title": "TextResourceContents",
        "type": "object"
      }
    },
    "properties": {
      "result": {
        "items": {
          "anyOf": [
            {
              "$ref": "#/$defs/TextContent"
            },
            {
              "$ref": "#/$defs/ImageContent"
            },
            {
              "$ref": "#/$defs/AudioContent"
            },
            {
              "$ref": "#/$defs/ResourceLink"
            },
            {
              "$ref": "#/$defs/EmbeddedResource"
            }
          ]
        },
        "title": "Result",
        "type": "array"
      }
    },
    "required": [
      "result"
    ],
    "title": "content_blocksOutput",
    "type": "object"
  }
);

export const dataclassOutput = createGeneratedTool<DataclassOutputInput, DataclassOutputOutput>(
  "dataclass-output",
  {
    "properties": {
      "x": {
        "title": "X",
        "type": "number"
      },
      "y": {
        "title": "Y",
        "type": "number"
      }
    },
    "required": [
      "x",
      "y"
    ],
    "title": "Point",
    "type": "object"
  }
);

export const dictionaryOutput = createGeneratedTool<DictionaryOutputInput, DictionaryOutputOutput>(
  "dictionary-output",
  {
    "additionalProperties": {
      "type": "integer"
    },
    "title": "dictionary_outputDictOutput",
    "type": "object"
  }
);

export const directResult = createGeneratedRawTool<DirectResultInput>(
  "direct-result",
);

export const disabledOutput = createGeneratedRawTool<DisabledOutputInput>(
  "disabled-output",
);

export const genericOutput = createGeneratedTool<GenericOutputInput, GenericOutputOutput>(
  "generic-output",
  {
    "properties": {
      "result": {
        "items": {
          "type": "string"
        },
        "title": "Result",
        "type": "array"
      }
    },
    "required": [
      "result"
    ],
    "title": "generic_outputOutput",
    "type": "object"
  }
);

export const imageHelper = createGeneratedRawTool<ImageHelperInput>(
  "image-helper",
);

export const primitiveOutput = createGeneratedTool<PrimitiveOutputInput, PrimitiveOutputOutput>(
  "primitive-output",
  {
    "properties": {
      "result": {
        "title": "Result",
        "type": "string"
      }
    },
    "required": [
      "result"
    ],
    "title": "primitive_outputOutput",
    "type": "object"
  }
);

export const typedDictOutput = createGeneratedTool<TypedDictOutputInput, TypedDictOutputOutput>(
  "typed-dict-output",
  {
    "properties": {
      "count": {
        "title": "Count",
        "type": "integer"
      },
      "name": {
        "title": "Name",
        "type": "string"
      }
    },
    "required": [
      "name",
      "count"
    ],
    "title": "Payload",
    "type": "object"
  }
);
