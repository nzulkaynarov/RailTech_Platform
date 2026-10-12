/** Разбор JSON Schema (pydantic) для формы настроек: ссылки, nullable, тип поля. */

export type JsonSchema = {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  format?: string;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
};

export type FieldKind =
  | "object"
  | "localized"
  | "string"
  | "text"
  | "number"
  | "integer"
  | "boolean"
  | "tags"
  | "number-tags"
  | "enum"
  | "multi-enum"
  | "unknown";

/** Подставить `$ref` и снять обёртку `anyOf: [X, null]`. */
export function resolve(
  schema: JsonSchema,
  root: JsonSchema,
): { schema: JsonSchema; nullable: boolean } {
  let current = schema;
  let nullable = false;
  if (current.anyOf) {
    const notNull = current.anyOf.filter((s) => s.type !== "null");
    nullable = notNull.length < current.anyOf.length;
    current = notNull[0] ?? {};
  }
  if (current.$ref) {
    const name = current.$ref.split("/").pop() ?? "";
    current = root.$defs?.[name] ?? {};
  }
  return { schema: current, nullable };
}

export function kindOf(schema: JsonSchema): FieldKind {
  const props = schema.properties;
  if (props && ["ru", "uz", "en"].every((k) => k in props)) return "localized";
  if (props) return "object";
  if (schema.enum) return "enum";
  if (schema.type === "array") {
    if (schema.items?.enum) return "multi-enum";
    const item = schema.items?.type;
    return item === "integer" || item === "number" ? "number-tags" : "tags";
  }
  if (schema.type === "integer" || schema.type === "number") return schema.type;
  if (schema.type === "boolean") return "boolean";
  if (schema.type === "string") return "string";
  return "unknown";
}

/** Значения формы → тело PUT: числа в списках и пустые строки nullable-полей. */
export function normalize(value: unknown, schema: JsonSchema, root: JsonSchema): unknown {
  const { schema: s, nullable } = resolve(schema, root);
  const kind = kindOf(s);
  if (kind === "object" || kind === "localized") {
    const source = (value ?? {}) as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(s.properties ?? {}).map(([key, child]) => [
        key,
        normalize(source[key], child, root),
      ]),
    );
  }
  if (kind === "number-tags" && Array.isArray(value))
    return value.map(Number).filter((n) => !Number.isNaN(n));
  if (nullable && (value === "" || value === undefined)) return null;
  return value;
}

export function bounds(schema: JsonSchema): { min?: number; max?: number } {
  const result: { min?: number; max?: number } = {};
  const min = schema.minimum ?? schema.exclusiveMinimum;
  const max = schema.maximum ?? schema.exclusiveMaximum;
  if (min !== undefined) result.min = min;
  if (max !== undefined) result.max = max;
  return result;
}
