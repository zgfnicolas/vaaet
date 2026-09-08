# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Registro local de bundles DVC, separado del runtime portable de serving."""

from .models import RegistryEntry, RegistryMaterializationPurpose, RegistryProvider
from .service import DvcRegistryService

__all__ = [
    "DvcRegistryService",
    "RegistryEntry",
    "RegistryMaterializationPurpose",
    "RegistryProvider",
]
