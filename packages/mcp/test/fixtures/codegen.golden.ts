import { createGeneratedTool } from "@belgie/mcp/internal";

export type ModelToolInput = {
  "choices"?: readonly ("a" | "b")[];
  "labels"?: Record<string, string>;
  "metrics"?: {
    "name": string;
    [key: string]: string | number;
  };
  "node": ModelToolInputNode;
  "pair": readonly [string, number];
  "value"?: "auto" | number | null;
};

export type ModelToolInputNode = {
  "name": string;
  "next"?: ModelToolInputNode | null;
};

export type ModelToolOutput = {
  "payload": {
    "id": string;
  } & {
    "active": boolean;
  };
};

export type ModelToolInput2 = {
  "limit"?: number;
};

export type ModelToolOutput2 = {
  "count": number;
};

/**
 * Build a model.
 * This closes * / safely.
 */
export const modelTool = createGeneratedTool<ModelToolInput, ModelToolOutput>(
  "model-tool",
  {
    "properties": {
      "payload": {
        "allOf": [
          {
            "properties": {
              "id": {
                "type": "string"
              }
            },
            "required": [
              "id"
            ],
            "type": "object"
          },
          {
            "properties": {
              "active": {
                "type": "boolean"
              }
            },
            "required": [
              "active"
            ],
            "type": "object"
          }
        ]
      }
    },
    "required": [
      "payload"
    ],
    "type": "object"
  }
);

export const modelTool2 = createGeneratedTool<ModelToolInput2, ModelToolOutput2>(
  "model_tool",
  {
    "properties": {
      "count": {
        "type": "integer"
      }
    },
    "required": [
      "count"
    ],
    "type": "object"
  }
);
