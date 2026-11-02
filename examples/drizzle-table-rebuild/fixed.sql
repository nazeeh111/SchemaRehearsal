PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_a_first` (
	`id` integer PRIMARY KEY,
	`name` text DEFAULT 'b'
);
--> statement-breakpoint
INSERT INTO `__new_a_first`(`id`, `name`) SELECT `id`, `name` FROM `a_first`;--> statement-breakpoint
DROP TABLE `a_first`;--> statement-breakpoint
ALTER TABLE `__new_a_first` RENAME TO `a_first`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_parents` (
	`id` integer PRIMARY KEY,
	`name` text DEFAULT 'b'
);
--> statement-breakpoint
INSERT INTO `__new_parents`(`id`, `name`) SELECT `id`, `name` FROM `parents`;--> statement-breakpoint
DROP TABLE `parents`;--> statement-breakpoint
ALTER TABLE `__new_parents` RENAME TO `parents`;--> statement-breakpoint
PRAGMA foreign_keys=ON;