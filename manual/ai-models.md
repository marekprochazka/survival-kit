# AI models

*Only on boxes installed with the **full** profile.*

The box can run small AI language models — offline, on this machine's own processor. You
talk to them in the terminal. (A chat page in the browser comes later.)

**What the machine needs:** at least **8 GB of RAM** and an i5-class processor (or
better). Small models answer at a few words per second; large ones (7B and up) crawl.

**Recommended models:** Llama 3.2 3B or Qwen 2.5 3B, in a 4-bit version (`Q4`, about 2 GB
each). Models never come with the box — bring them on a USB stick as a **`.gguf`** file.

## Adding a model from a USB stick

Plug in the stick, open a terminal, and run (with your stick's and file's names):

    printf 'FROM /run/media/deck/<stick>/<model>.gguf\n' > Modelfile
    ollama create <name> -f Modelfile

`ollama create` copies the model into the box; the stick can be removed afterwards.

## Using it

    ollama run <name>        # chat; leave with /bye
    ollama list              # the models on this box
    ollama rm <name>         # delete one (frees its disk space)
