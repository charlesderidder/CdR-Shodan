# CdR-Shodan

Compacte GUI-client voor de Shodan API, gebouwd met Python en Tkinter.

## Wat is dit?

CdR-Shodan biedt een desktopinterface om Shodan-data op te zoeken zonder commandline.
Je kunt onder andere hosts opvragen, zoeken op query's en account/API-info bekijken.

## Vereisten

- Python 3.10+
- Tkinter (meestal standaard bij Python)
- `requests` (aanbevolen)
- Een geldige Shodan API key

## Snel starten

1. Installeer afhankelijkheden:
	```bash
	pip install requests
	```
2. Start de applicatie:
	```bash
	python shodan.py
	```
3. Vul bij eerste start je Shodan API key in.

## Platformnotities

- Windows: instellingen worden opgeslagen in het register (met JSON-fallback).
- Linux zonder grafische sessie: het script probeert automatisch via `xvfb-run` te starten.

## Disclaimer

Gebruik deze tool alleen op systemen en netwerken waarvoor je toestemming hebt.
