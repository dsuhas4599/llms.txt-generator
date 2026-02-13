"""
llms.txt generator: turn PageInfo list into spec-compliant markdown.
"""
from .generator import GeneratorOptions, generate_llms_txt

__all__ = ["generate_llms_txt", "GeneratorOptions"]
