# Language

The **Language** tile (<https://language.deck>) translates text and looks up words — no
internet needed. It has three tabs.

## Translate

Pick the language **From** and **To**, type or paste the text on the left and press
**Translate** (or Ctrl+Enter). **⇄** swaps the languages (and puts the translation on the
left, to translate it back). **Copy** copies the translation. Up to 5 000 characters at a
time; a paragraph takes a few seconds on a slow computer.

Built in: **English → Czech** and **Czech → English**. The translations come from small
translation models that run on this box (Argos Translate, made from the OPUS-MT models of
the University of Helsinki, CC-BY 4.0).
They are good for everyday text; check anything important with someone who speaks the
language.

A language pair the box has no model for goes **through English** when it can, e.g. German →
English → Czech once a German → English model is added. Such pairs are marked
*(via English)*; the result is a bit rougher.

## Dictionary

Type a word and press **Look up**. Built in: **WordNet**, an English dictionary (meanings,
examples, related words). A word that isn't there shows words that start the same — click
one to look it up. With more dictionaries added, choose one above the search box.

## Thesaurus

Type an English word and press **Find synonyms**. The words come from the **Moby
Thesaurus** — a long list per word, in alphabetical order (not grouped by meaning). Click a
word to see its synonyms. The thesaurus is English only and comes with the box; there is no
way to add others.

## More languages

Bring files on a USB stick and import them in [Content](content.html), *Languages* section:

- **Translation models** (`.argosmodel`): the Argos Translate list,
  <https://www.argosopentech.com/argospm/index/> — one file per direction (e.g.
  `translate-de_en-….argosmodel` for German → English and `translate-en_de-…` back).
- **Dictionaries** (`.dictd.tar.xz`): FreeDict, <https://freedict.org/downloads/> — pick a
  pair (e.g. English–Czech) and download the **dictd** file
  (`freedict-eng-ces-….dictd.tar.xz`).

Reload the Language page afterwards. An imported model named like a built-in one (e.g.
`translate-en_cs-…`) replaces it until you delete the import. Like books and maps, they can
be saved to a big drive.
