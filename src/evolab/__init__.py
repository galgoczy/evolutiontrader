"""EvolutionTrader labor: stratégia-populáció, statisztikai bíró, LLM-kutató."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("evolab")
except PackageNotFoundError:  # forrásból futtatva, telepítés nélkül
    __version__ = "0.0.0+local"
