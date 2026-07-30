WHY THIS FOLDER IS EMPTY
=========================
The offline speech recognition model ("small.en", in CTranslate2 format) is
a large binary file (several hundred MB). It cannot be generated as source
code and cannot be fetched automatically as part of this project, because:

  1. It is a binary model download, not something that can be "written" as
     a file the way code can.
  2. It must be downloaded from Hugging Face's servers, and this build
     environment only has network access to package registries
     (pypi.org, npmjs.com, github.com) - not huggingface.co.

HOW TO GET IT (do this once, on a machine with internet access)
==================================================================
1. Make sure you have already run:
       pip install -r requirements.txt

2. Run this one-line command from the DoctorVoiceNotes project folder:

       python -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8', download_root='models/small.en')"

   This downloads the model directly into models/small.en/ (that is what
   download_root does - no manual copying from a cache folder needed).

3. When it finishes, this folder should contain files such as:
       model.bin
       config.json
       tokenizer.json  (or vocabulary.txt, depending on model version)

4. From that point on, the app runs 100% offline - it will not attempt to
   contact the internet again as long as these files remain in this folder.

IF YOU ARE BUILDING THE FINAL OFFLINE INSTALLER FOR THE DOCTOR'S LAPTOP
==========================================================================
Do step 2 on YOUR machine (the one with internet), then make sure these
model files are included when you package the app with PyInstaller (see
the Phase 7 build script and .spec file). The doctor's laptop itself never
needs internet access, before or after installation.
