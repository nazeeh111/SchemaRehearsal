import { sqliteTable, integer, text } from "drizzle-orm/sqlite-core";

export const aFirst = sqliteTable("a_first", {
  id: integer("id").primaryKey(),
  name: text("name").default("a"),
});

export const parents = sqliteTable("parents", {
  id: integer("id").primaryKey(),
  name: text("name").default("a"),
});

export const children = sqliteTable("children", {
  id: integer("id").primaryKey(),
  parentId: integer("parent_id").notNull().references(() => parents.id, { onDelete: "cascade" }),
});
