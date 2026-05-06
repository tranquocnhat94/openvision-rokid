# Perception

Perception owns local visual evidence.

Source package:

- `openvision_jetson/perception_graph.py`
- `openvision_jetson/yolo26_rokid_adapter.py`
- `openvision_jetson/deepstream_yolo26_worker.py`
- `openvision_jetson/face_identity_adapter.py`
- `openvision_jetson/face_identity_worker.py`
- `openvision_jetson/contact_identity.py`
- `openvision_jetson/people_registry.py`

Responsibilities:

- frame sampling;
- object detections;
- track IDs;
- crop extraction;
- local contact identity reminders from enrolled crops;
- user-managed People Registry metadata linked to Immich people;
- local face embedding stream for named-contact reminders;
- crop retention policy;
- selected target continuity;
- perception graph;
- cloud evidence request packaging.

YOLO26 reuse must go through a separate Rokid adapter path and must not interfere with the existing Ring/security runtime.

For product RV101 live skills, use a separate OpenVision YOLO26 stream worker.
The current production worker can be NVIDIA DeepStream: it creates an
OpenVision RTSP relay from the RV101 H.264 live sample bus, launches a
per-session `deepstream-app` pipeline with OpenVision YOLO26 configs, consumes
DeepStream MQTT detection events, and posts bbox frames back to the adapter.
Those frames are detector metadata only. Product bbox authority belongs to the
Rokid `Yolo26LiveStabilizer`, which filters, NMSes, track-holds, and smooths
detections before they enter the perception graph, skills, HUD, or Ops preview.
DeepStream OSD H.264 may remain as a diagnostic preview, but it must not be the
product bbox renderer. All YOLO26 paths must remain OpenVision-specific; Ring,
security, or surveillance paths/sources are rejected.

The contact identity store is a local OpenVision runtime DB. It can enroll
user-labeled crop/image samples, match live `target_finder` candidates, and
return `display_name`/confidence to the HUD without adding another command brain.

The People Registry stores extended metadata such as aliases, phone/address,
social links, and notes while keeping photos and thumbnails in Immich. Sync runs
through typed Jetson API endpoints so target/person skills can resolve names and
metadata without copying the user's photo library into OpenVision.

`remember_person` is the capture path for adding new people from the glasses:
Jetson requests a fresh snapshot, uploads the image bytes to Immich, records
metadata-only capture state in the People Registry, and waits for Immich face
processing plus the next People sync to expose the new face group in Face UI.
When a name is provided, Jetson can also try to enroll a local identity sample
for immediate `target_finder` matching; image bytes are not stored in the
People Registry DB.

For named people such as `tìm Trâm`, prefer the dedicated face identity worker
over sharing the Ring YOLO26 runtime. YOLO26 is useful for person/object boxes;
the face worker adds on-demand face boxes and SFace embeddings at low FPS while
`target_finder` live video is active.
