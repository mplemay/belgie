import { createGeneratedTool } from "@belgie/mcp/internal";

export type GetTimeInput = Record<string, never>;

export interface GetTimeOutput {
  result: readonly GetTimeOutputTextContent[];
}

export interface GetTimeOutputAnnotations {
  audience?: readonly ("user" | "assistant")[] | null;
  lastModified?: string | null;
  priority?: number | null;
}

export interface GetTimeOutputTextContent {
  _meta?: Record<string, unknown> | null;
  annotations?: GetTimeOutputAnnotations | null;
  text: string;
  type?: "text";
}

/** Get the current server time in ISO 8601 format. */
export const getTime = createGeneratedTool<GetTimeInput, GetTimeOutput>("get-time", {
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
    TextContent: {
      description: "Text provided to or from an LLM.",
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
        text: {
          title: "Text",
          type: "string",
        },
        type: {
          const: "text",
          default: "text",
          title: "Type",
          type: "string",
        },
      },
      required: ["text"],
      title: "TextContent",
      type: "object",
    },
  },
  properties: {
    result: {
      items: {
        $ref: "#/$defs/TextContent",
      },
      title: "Result",
      type: "array",
    },
  },
  required: ["result"],
  title: "get_timeOutput",
  type: "object",
});
