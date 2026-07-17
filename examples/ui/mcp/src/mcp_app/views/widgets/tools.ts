import { createGeneratedTool } from "@belgie/mcp/internal";

export type GetTimeInput = Record<string, never>;

export type GetTimeOutput = {
  "time": string;
};

/** Get the current server time in ISO 8601 format. */
export const getTime = createGeneratedTool<GetTimeInput, GetTimeOutput>(
  "get-time",
  {
    "properties": {
      "time": {
        "title": "Time",
        "type": "string"
      }
    },
    "required": [
      "time"
    ],
    "title": "TimeResult",
    "type": "object"
  }
);
