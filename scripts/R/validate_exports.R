#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) stop("usage: validate_exports.R <jsonl>")
if (!requireNamespace("jsonlite", quietly = TRUE)) stop("install jsonlite in scripts/R renv")

lines <- readLines(args[[1]], warn = FALSE)
records <- lapply(lines[nzchar(lines)], jsonlite::fromJSON, simplifyVector = FALSE)
required <- c("source_url")
missing <- vapply(records, function(x) any(!required %in% names(x)), logical(1))

cat("records:", length(records), "\n")
cat("missing_required:", sum(missing), "\n")
if (any(missing)) quit(status = 1)
