# Content sticks

Two USB sticks carry content for this box. Everything on them works offline and comes in
through the **Content** tile — see [Content](content.html). Both sticks are formatted
**exFAT** (FAT32 can't hold files over 4 GB), and each has a `README.txt` that says the same
as this page, for reading on any computer.

## KIT-WIKI — the offline library (128 GB stick)

25 wiki books, about **94 GB**, downloaded 2026-10-31 from <https://library.kiwix.org>.

| Group | Books | Size |
|---|---|---|
| Encyclopedias | Wikipedia in English (all articles, text only), Wikipedia in Czech (with pictures) | 62.7 GB |
| Medicine | WikiMed, LibreTexts Medicine | 3.5 GB |
| Practical know-how | Wikibooks, iFixit repair guides, Appropedia, Energypedia | 9.7 GB |
| Travel | Wikivoyage | 1.1 GB |
| Questions and answers | Stack Exchange: DIY, Electronics, Gardening, Cooking, Outdoors, Amateur radio, Sustainable living, Medical sciences, Ask Ubuntu, Unix & Linux | 11.9 GB |
| Textbooks | LibreTexts Biology, Chemistry, Engineering | 5.1 GB |
| Tools | PhET science simulations, Arch Wiki, Nix documentation | 0.2 GB |

**Importing:** under *Wiki books*, choose **a folder** and pick the stick to take every book,
or pick single files. All of it needs about 94 GB — on a small notebook, save to an
[added drive](content.html#adding-a-big-drive) or take only what you need.

## KIT-MODELS — AI models (16 GB stick)

*For boxes installed with the full profile.* Five model files, about **13.1 GB**, from
Hugging Face; all are open source (Apache-2.0).

The number in a model's name (2B, 4B, 9B) is its size in billions of *parameters*: bigger
models give better answers, but are slower and need more memory (RAM).

| Model | File | Pick it when |
|---|---|---|
| Qwen3.5 2B | 1.3 GB | the machine is old or weak; fastest |
| **Qwen3.5 4B** | 2.7 GB | **the usual choice** — 8 GB RAM |
| Gemma 4 E2B | 3.1 GB | 8 GB RAM; a second opinion from a different maker (Google) — worth trying for Czech |
| Qwen3.5 9B | 5.7 GB | 16 GB RAM or more; best answers, slowest |
| EmbeddingGemma 2 | 0.3 GB | not for chatting — kept for a future "search by meaning" |

`Q4_K_M` in a file name means the model is compressed to about 4 bits per number so it fits
in memory; the quality loss is small.

**Importing:** under *AI models*, choose **Import a model** and pick one file. Import as many
as you like and choose between them in the [Chat](chat.html). More about models:
[AI models](ai-models.html).

## Checking a stick

Each stick has a `SHA256SUMS` file with the official fingerprint of every file. Open the
stick in the file manager, then a terminal there, and run:

    sha256sum -c SHA256SUMS

Every line should end with `OK`. Flash memory slowly fades when it isn't used — plug the
sticks in and check them about once a year.
