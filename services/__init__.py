# services package -- one subpackage per independently deployable
# microservice (see Server_Design.md, Part B). Each subpackage's
# Dockerfile builds a separate container image; this file only exists
# so `services.<name>.main` is importable as a Python module path.
