"""Copper layer depths from KiCad's saved stackup, with an explicit fallback."""
from sexpdata import loads


def copper_stackup(text, layers, board_thickness_mm):
    def entries(node, tag):
        return [x for x in node if isinstance(x, list) and x and str(x[0]) == tag]

    root = loads(text)
    setup = entries(root, 'setup')
    stack = entries(setup[0], 'stackup') if setup else []
    depths, thicknesses = {}, {}
    if stack:
        z = 0.0
        for entry in entries(stack[0], 'layer'):
            name = str(entry[1])
            # KiCad may split a dielectric into sublayers separated by add_sublayer.
            thickness = sum(float(x[1]) for x in entries(entry, 'thickness'))
            if name in layers:
                depths[name] = z + thickness / 2
                if thickness > 0:
                    thicknesses[name] = thickness * 1000
            if name in layers or name.startswith('dielectric'):
                z += thickness
        if set(depths) == set(layers):
            origin = depths[layers[0]]
            return {'layer_order': layers, 'layer_depth_mm': {k: v-origin for k, v in depths.items()},
                    'layer_copper_thickness_um': thicknesses, 'stackup_source': 'saved KiCad stackup'}
    count = len(layers)
    return {'layer_order': layers,
            'layer_depth_mm': {name: board_thickness_mm*i/max(count-1, 1) for i, name in enumerate(layers)},
            'layer_copper_thickness_um': {},
            'stackup_source': 'uniform spacing fallback; no complete saved stackup'}
