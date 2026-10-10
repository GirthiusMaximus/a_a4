"""skinprobe: read a Rust item skin's files and score them for IP risk.

Formats handled (both verified against a working importer, see README):
  modern  manifest/manifest.txt + one folder per Unity texture slot
  legacy  raw Unity project upload: .mat + .meta + .tga/.jpg/.png/.psd (+ meta.asset for groups)
"""

__all__ = ["manifest", "imaging", "ipcheck", "providers", "scan"]
__version__ = "0.1.0"
