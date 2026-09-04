"""Vendored copy of the OSI reference Python types.

Source: https://github.com/open-semantic-interchange/OSI
        python/src/osi (commit 056b5aadc555c0af123af26720324e940a7ee92d)
License: Apache-2.0 (c) Open Semantic Interchange contributors
Vendored because `osi-python` is not yet published to PyPI. Replace this
package with the real dependency once it is published.
"""

from .models import (
    OSIAIContext,
    OSIAIContextObject,
    OSICustomExtension,
    OSIDataset,
    OSIDialect,
    OSIDialectExpression,
    OSIDimension,
    OSIDocument,
    OSIExpression,
    OSIField,
    OSIMetric,
    OSIRelationship,
    OSISemanticModel,
    OSIVendor,
)

__all__ = [
    "OSIAIContext",
    "OSIAIContextObject",
    "OSICustomExtension",
    "OSIDataset",
    "OSIDialect",
    "OSIDialectExpression",
    "OSIDimension",
    "OSIDocument",
    "OSIExpression",
    "OSIField",
    "OSIMetric",
    "OSIRelationship",
    "OSISemanticModel",
    "OSIVendor",
]
