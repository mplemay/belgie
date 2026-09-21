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

export type ContentBlocksOutput = RawToolResult;

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
  "count"?: number;
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

export const contentBlocks = createGeneratedRawTool<ContentBlocksInput>(
  "content-blocks",
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
      "name"
    ],
    "title": "Payload",
    "type": "object"
  }
);
