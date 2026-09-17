"""MMH3 Spatial Tile Media — inject wired image / video / audio into tile_config.

Sits between MMH3 Spatial Tile Editor and MMH3 Spatial Extend Video so you can
drive references from Load Image / Load Video / Load Audio nodes instead of
only picking files in the dock panel.

The editor stays a pure-information node. This node is the only place tensors
enter the tile_config dict. Spatial Extend encodes them at sample time using
the same Ref2VA rules as MiniMaxH3ReferenceToVideo:

    images  -> <Picture i>
    videos  -> optional paired soundtrack <Audio j> then <Video k>
    audios  -> standalone <Audio j>
"""
from __future__ import annotations

from comfy_api.latest import io

H3_REFS = io.Custom("H3_REFS")


def _empty_h3_refs():
    return {
        "pictures": [],
        "videos": [],
        "video_audios": [],
        "audios": [],
        "items": [],
    }


def _normalize_h3_refs(references):
    if not isinstance(references, dict):
        return _empty_h3_refs()
    return {
        "pictures": list(references.get("pictures") or []),
        "videos": list(references.get("videos") or []),
        "video_audios": list(references.get("video_audios") or []),
        "audios": list(references.get("audios") or []),
        "items": list(references.get("items") or []),
    }


APPLY_MODES = [
    "append_ref2va",
    "replace_ref2va",
    "selected_tile",
]


def _as_list(group):
    """Normalize an Autogrow dict / single value / None into an ordered list."""
    if group is None:
        return []
    if isinstance(group, dict):
        items = []
        for key in sorted(group.keys(), key=lambda k: (len(str(k)), str(k))):
            items.append(group[key])
        return items
    if isinstance(group, (list, tuple)):
        return list(group)
    return [group]


def _keep(value):
    return value is not None


class MMH3SpatialTileMedia(io.ComfyNode):
    """Attach wired media (and optional Fun Control video) to a tile_config."""

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="MMH3SpatialTileMedia",
            display_name="MMH3 Spatial Tile Media",
            category="model/conditioning/minimax",
            description=(
                "Inject Load Image / Load Video / Load Audio tensors into a "
                "Spatial Tile Editor config. Connect tile_config in, wire media, "
                "then send tile_config out to MMH3 Spatial Extend Video. "
                "Ref2VA tiles receive wired stills as extra <Picture n> blocks, "
                "video frame batches as <Video k> (optional paired soundtrack), "
                "and standalone clips as <Audio j>. Fun ControlNet is optional: "
                "this node only carries the control video; apply the official "
                "Fun ControlNet patch on the MODEL going into Sample Params, or "
                "use the matching sockets on Spatial Extend Video."
            ),
            search_aliases=[
                "h3 tile media", "h3 wired refs", "h3 audio ref",
                "h3 video ref", "h3 load image tile",
            ],
            inputs=[
                io.Dict.Input(
                    "tile_config",
                    tooltip="Output of MMH3 Spatial Tile Editor (or another Tile Media node).",
                ),
                H3_REFS.Input(
                    "references", optional=True,
                    tooltip="Fantastic H3 Media Loader bundle. Merged onto tile_config and passed through. Pictures/videos/audios become wired Ref2VA media.",
                ),
                io.Combo.Input(
                    "apply_mode",
                    options=APPLY_MODES,
                    default="append_ref2va",
                    tooltip=(
                        "append_ref2va: add wired media after each Ref2VA tile's "
                        "editor stills. replace_ref2va: ignore editor stills on "
                        "Ref2VA tiles and use only wired media. selected_tile: "
                        "only the tile_index tile (0-based) receives wired media."
                    ),
                ),
                io.Int.Input(
                    "tile_index",
                    default=1, min=0, max=11,
                    tooltip="Used when apply_mode is selected_tile. 0 is the left/anchor tile.",
                ),
                io.Autogrow.Input(
                    "images", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input(
                            "image",
                            tooltip="Still reference from a Load Image (or similar) node.",
                        ),
                        prefix="image_", min=0, max=9,
                    ),
                ),
                io.Autogrow.Input(
                    "videos", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Image.Input(
                            "video",
                            tooltip="Reference video as an IMAGE batch at 24 fps (VHS_LoadVideo IMAGE output).",
                        ),
                        prefix="video_", min=0, max=3,
                    ),
                ),
                io.Autogrow.Input(
                    "video_audios", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input(
                            "video_audio",
                            tooltip="Soundtrack paired with the same-numbered video_ socket.",
                        ),
                        prefix="video_audio_", min=0, max=3,
                    ),
                ),
                io.Autogrow.Input(
                    "audios", optional=True,
                    template=io.Autogrow.TemplatePrefix(
                        input=io.Audio.Input(
                            "audio",
                            tooltip="Standalone voice / music / SFX reference from Load Audio.",
                        ),
                        prefix="audio_", min=0, max=3,
                    ),
                ),
                io.Image.Input(
                    "fun_control_video", optional=True,
                    tooltip=(
                        "Preprocessed Fun ControlNet video (pose/depth/canny/…). "
                        "Stored on tile_config. Spatial Extend crops it per tile when "
                        "fun_control_fit is canvas_crop."
                    ),
                ),
                io.Combo.Input(
                    "fun_control_fit",
                    options=["canvas_crop", "tile_match"],
                    default="canvas_crop",
                    tooltip=(
                        "canvas_crop: control video is the FULL plan canvas; each tile "
                        "gets its placement crop so pose is not stretched across panels. "
                        "tile_match: resize the whole control clip to the target tile size."
                    ),
                ),
            ],
            outputs=[
                io.Dict.Output(
                    "tile_config",
                    tooltip="Editor config plus wired_media / h3_refs / fun_control for Spatial Extend Video.",
                ),
                H3_REFS.Output(
                    "references",
                    tooltip="Passthrough Fantastic H3 references bundle for Prompt Builder / upscale.",
                ),
                io.String.Output(
                    "ref_map",
                    tooltip="Which H3 tags the wired media will become on target tiles.",
                ),
            ],
        )

    @classmethod
    def execute(cls, tile_config, apply_mode="append_ref2va", tile_index=1,
                images=None, videos=None, video_audios=None, audios=None,
                fun_control_video=None, fun_control_fit="canvas_crop",
                references=None) -> io.NodeOutput:
        if not isinstance(tile_config, dict):
            raise ValueError("tile_config must be the dict from MMH3 Spatial Tile Editor")

        refs = _normalize_h3_refs(references)
        if not any(refs[k] for k in ("pictures", "videos", "audios", "items")):
            refs = _normalize_h3_refs(tile_config.get("h3_refs"))

        img_list = [v for v in _as_list(images) if _keep(v)]
        vid_list = [v for v in _as_list(videos) if _keep(v)]
        va_list = _as_list(video_audios)
        aud_list = [v for v in _as_list(audios) if _keep(v)]

        # Media Loader pictures/videos/audios become wired refs when the
        # explicit Load Image/Video/Audio sockets were left empty.
        if not img_list:
            img_list = [v for v in refs.get("pictures") or [] if _keep(v)]
        if not vid_list:
            vid_list = [v for v in refs.get("videos") or [] if _keep(v)]
            va_list = list(refs.get("video_audios") or [])
        if not aud_list:
            aud_list = [v for v in refs.get("audios") or [] if _keep(v)]

        paired_audio = []
        for i, _frames in enumerate(vid_list):
            paired_audio.append(va_list[i] if i < len(va_list) else None)

        config = dict(tile_config)
        config["wired_media"] = {
            "apply_mode": apply_mode if apply_mode in APPLY_MODES else "append_ref2va",
            "tile_index": int(tile_index),
            "images": img_list,
            "videos": vid_list,
            "video_audios": paired_audio,
            "audios": aud_list,
        }
        config["h3_refs"] = refs
        if fun_control_video is not None:
            config["fun_control_video"] = fun_control_video
        config["fun_control_fit"] = fun_control_fit if fun_control_fit in ("canvas_crop", "tile_match") else "canvas_crop"

        n_img, n_vid, n_aud = len(img_list), len(vid_list), len(aud_list)
        lines = [
            f"apply_mode={config['wired_media']['apply_mode']}  tile_index={tile_index}",
            f"wired stills: {n_img}   videos: {n_vid}   standalone audio: {n_aud}",
        ]
        pic = 1
        # Official presentation order on the *wired* extras, after any editor stills
        # that append_ref2va keeps. Exact Picture index depends on how many file
        # stills that tile already has; Spatial Extend prints the final map.
        if n_img:
            lines.append("wired images become extra <Picture n> after editor stills")
            pic  # kept for readability
        vid_tag = 1
        aud_tag = 1
        for i, frames in enumerate(vid_list):
            frames_n = int(frames.shape[0]) if hasattr(frames, "shape") else "?"
            if paired_audio[i] is not None:
                lines.append(f"<Audio {aud_tag}> soundtrack + <Video {vid_tag}> ({frames_n} frames)")
                aud_tag += 1
            else:
                lines.append(f"<Video {vid_tag}> ({frames_n} frames, no soundtrack)")
            vid_tag += 1
        for i in range(n_aud):
            lines.append(f"<Audio {aud_tag}> standalone")
            aud_tag += 1
        if fun_control_video is not None:
            fc_n = int(fun_control_video.shape[0]) if hasattr(fun_control_video, "shape") else "?"
            lines.append(
                f"fun_control_video carried ({fc_n} frames), fit={config.get('fun_control_fit')}"
            )
        if refs["items"] or refs["pictures"]:
            lines.append(
                f"H3_REFS passthrough: {len(refs['pictures'])} pic, "
                f"{len(refs['videos'])} vid, {len(refs['audios'])} aud"
            )
        if n_img + n_vid + n_aud == 0 and fun_control_video is None:
            lines.append("(no extra sockets — using H3_REFS / editor stills only)")

        return io.NodeOutput(config, refs, "\n".join(lines))
