"""Helpers that pair Spatial Extend with LBH MiniMax H3 Latent Upscaler.

This pack does not vendor the neural upscaler weights. Install
https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler
and put the checkpoint in models/latent_upscale_models/.

Typical graph:

    Spatial Extend.latent
        → Minimax H3 Latent Upscaler (3D)
              width  ← Tile Editor.width  * scale
              height ← Tile Editor.height * scale
        → (optional) MMH3 Split Upscale refine
        → VAE Decode
"""
from comfy_api.latest import io


CANVAS_MULTIPLE = 32


def _snap32(v, minimum=32):
    v = int(round(float(v)))
    return max(minimum, int(round(v / CANVAS_MULTIPLE) * CANVAS_MULTIPLE))


class MMH3SpatialLatentUpscaleSize(io.ComfyNode):
    """Turn a Spatial Tile Editor canvas into LBH upscaler target W/H."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MMH3SpatialLatentUpscaleSize",
            display_name="MMH3 Spatial Latent Upscale Size",
            category="model/latent/minimax",
            description=(
                "Compute target pixel size for LBH Minimax H3 Latent Upscaler (3D) "
                "from a Spatial Tile Editor canvas. Does not run the upscaler — "
                "wire width/height into that node. scale=1 keeps generate resolution; "
                "scale=2 is the usual hires pass."
            ),
            search_aliases=["h3 latent upscale size", "h3 target size"],
            inputs=[
                io.Dict.Input("tile_config",
                              tooltip="From MMH3 Spatial Tile Editor."),
                io.Float.Input("scale", default=2.0, min=1.0, max=4.0, step=0.05,
                               tooltip="Multiply canvas W/H. 1 = no extra upscale, 2 = 2× latent upscale."),
                io.Int.Input("width_override", default=0, min=0, max=8192, step=32,
                             tooltip="If > 0, use this instead of tile_config total_width * scale."),
                io.Int.Input("height_override", default=0, min=0, max=8192, step=32,
                             tooltip="If > 0, use this instead of tile_config total_height * scale."),
            ],
            outputs=[
                io.Int.Output("width", tooltip="Target pixel width for the LBH 3D upscaler."),
                io.Int.Output("height", tooltip="Target pixel height for the LBH 3D upscaler."),
                io.Float.Output("scale", tooltip="Echo of the scale used."),
            ],
        )

    @classmethod
    def execute(cls, tile_config, scale=2.0, width_override=0, height_override=0) -> io.NodeOutput:
        if not isinstance(tile_config, dict):
            raise ValueError("tile_config must come from MMH3 Spatial Tile Editor")
        base_w = int(tile_config.get("total_width") or 0)
        base_h = int(tile_config.get("total_height") or 0)
        if base_w < 32 or base_h < 32:
            tiles = tile_config.get("tiles") or []
            if tiles:
                base_w = max(base_w, int(tiles[0].get("width") or 0))
                base_h = max(base_h, int(tiles[0].get("height") or 0))
        tw = int(width_override) if int(width_override or 0) >= 32 else _snap32(base_w * float(scale))
        th = int(height_override) if int(height_override or 0) >= 32 else _snap32(base_h * float(scale))
        print(f"[MMH3SpatialLatentUpscaleSize] canvas {base_w}x{base_h} × {scale} -> {tw}x{th}")
        return io.NodeOutput(tw, th, float(scale))
