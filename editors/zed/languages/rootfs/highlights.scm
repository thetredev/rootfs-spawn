; Keywords / structural punctuation

"imports" @keyword

"=" @operator

["[" "]" "{"] @punctuation.bracket

(comment) @comment

; imports = [ ... ]

(import_path) @string.special.path

; name = value / name = { ... }

(assignment name: (identifier) @property)

(block_def name: (identifier) @property)

(string) @string

(bare_string) @string

(block_content_line) @embedded
