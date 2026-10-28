# Method

ArtPrompt hides a sensitive term behind ASCII art and asks the model to recover
the masked instruction. The current script uses a deterministic longest-word
mask and a simple horizontal banner to keep the reproduction self-contained.
