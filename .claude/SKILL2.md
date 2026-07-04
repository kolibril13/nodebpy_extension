---
name: nodebpy-group-import
description: >-
  How to structure nodebpy code so the Nodes-to-Code panel's "Run → Node Group"
  operator drops the result into the open Node Editor as a cursor-attached group
  node. Use when writing/debugging nodebpy snippets meant to be run from the
  extension's panel, especially CustomGeometryGroup / CustomShaderGroup classes,
  or when "Run → Node Group" reports "Ran code from the panel" and drops nothing.
---

# nodebpy "Run → Node Group" — how to structure code

```py
from nodebpy import geometry as g, TreeBuilder
from nodebpy.builder import CustomGeometryGroup


class ValueIsOneOf4(CustomGeometryGroup):
    _name = "Value Is One Of (4)"
    _color_tag = "CONVERTER"

    def _build_group(self, tree):
        value = tree.inputs.integer("Value", 0)
        b = tree.inputs.integer("B", 1)
        b_1 = tree.inputs.integer("B", 10)
        b_2 = tree.inputs.integer("B", 23)
        b_3 = tree.inputs.integer("B", 43)
        result = tree.outputs.boolean("Result")

        (
            (
                g.Compare.integer.equal(value, b).o.result
                | g.Compare.integer.equal(value, b_1)
                | (
                    g.Compare.integer.equal(value, b_2).o.result
                    | g.Compare.integer.equal(value, b_3)
                )
            )
            >> result
        )
```