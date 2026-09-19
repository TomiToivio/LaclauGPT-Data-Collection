#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) stop("usage: import_readtext.R <path/glob>")
if (!requireNamespace("readtext", quietly = TRUE)) stop("install readtext in scripts/R renv")

corpus <- readtext::readtext(args[[1]])
print(utils::head(corpus))
