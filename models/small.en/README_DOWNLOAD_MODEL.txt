DOCTOR VOICE NOTES - SPEECH MODEL SETUP
=========================================

This folder must contain the CTranslate2-converted Whisper "small.en"
model files before the app will run. This is a ONE-TIME setup step,
done once on a machine with internet access - the finished app itself
never touches the internet (PRD Section 15).

You need these files to end up directly inside this folder
(models\small.en\), not in a subfolder:

    model.bin
    config.json
    tokenizer.json
    vocabulary.txt   (or vocabulary.json, depending on model version)

--------------------------------------------------------------------
OPTION A (recommended): download the pre-converted model
--------------------------------------------------------------------
Systran maintains ready-to-use CTranslate2 conversions of every
official Whisper model size on Hugging Face. This avoids running any
conversion tooling yourself.

1. On a machine WITH internet access, with Python 3.12 and this
   project's virtual environment active (see README.md), run:

       pip install huggingface_hub
       python -c "from huggingface_hub import snapshot_download; print(snapshot_download('Systran/faster-whisper-small.en'))"

   This prints a local cache folder path once the download finishes.

2. Copy every file from that printed folder into this folder
   (models\small.en\) - NOT the folder itself, its contents.

3. Confirm model.bin is now directly at:
       DoctorVoiceNotes\models\small.en\model.bin

--------------------------------------------------------------------
OPTION B: convert it yourself from the original Whisper weights
--------------------------------------------------------------------
Only needed if you want a model size/variant Systran hasn't already
converted, or want to convert from a fine-tuned checkpoint.

1. On a machine with internet access:

       pip install ctranslate2 transformers[torch]
       ct2-transformers-converter --model openai/whisper-small.en \
           --output_dir models\small.en --quantization int8

   --quantization int8 matches this project's default
   whisper_compute_type setting (config_manager.py) - if you change
   one, change the other to match, or transcription will still work
   but silently ignore the requested compute type.

2. The converter writes directly into models\small.en\ - no copying
   step needed for this option.

--------------------------------------------------------------------
CHOOSING A DIFFERENT MODEL SIZE
--------------------------------------------------------------------
"small.en" is this project's default (config_manager.py's
DEFAULT_SETTINGS["whisper_model_size"]) - a reasonable balance of
accuracy and CPU/memory cost for the PRD's NFRs (Section 7: under 30%
CPU, under 1GB RAM). Larger models (medium.en, large-v3) are more
accurate but slower and heavier; smaller ones (base.en, tiny.en) are
faster but noticeably less accurate for medical dictation. To use a
different size:

1. Repeat Option A or B above with the new size name instead of
   "small.en" (e.g. Systran/faster-whisper-medium.en), into a
   differently-named folder, e.g. models\medium.en\.
2. In the app, open Settings and note there is currently no UI field
   for this (PRD FR-09 lists it as a config-level setting, not exposed
   in the dialog - see Section 5 of the Phase 6 handoff notes if this
   needs adding). For now, edit config\settings.json by hand:
       "whisper_model_size": "medium.en"
   and restart the app.

--------------------------------------------------------------------
VERIFYING THE MODEL WORKS BEFORE PACKAGING THE INSTALLER
--------------------------------------------------------------------
Run the app from source (python main.py) after placing the model
files here. The status bar should change from "Loading speech
model..." to "Ready" within a few seconds, and the Start button should
become clickable. If instead you see a "Doctor Voice Notes - Fatal
Error" dialog, re-check that model.bin is directly inside
models\small.en\ and not one folder level too deep - this is the most
common mistake with Option A above.