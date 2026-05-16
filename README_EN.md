# UV Island Normalizer

A Blender add-on that normalizes UV island sizes based on 3D world space scale.

---

## Overview

Register a reference UV island, then automatically match the texel density of other islands to it.  
Ideal for situations like: *"I added new geometry later and want its UV to match the exact scale of already-unwrapped meshes."*

---

## Compatibility

| Blender Version | Status |
|---|---|
| 3.6 | ✅ Primary target |
| 4.0 – 4.1 | ✅ Supported |
| 4.2 – 5.1 | ✅ Supported (Extension format) |

---

## Installation

### Blender 3.6 – 4.1

1. Open **Edit > Preferences > Add-ons**
2. Click **Install** (top right)
3. Select the ZIP file and click **Install Add-on**
4. Enable **UV: UV Island Normalizer** in the list

### Blender 4.2 and later (including 5.x)

1. Open **Edit > Preferences**
2. Go to the **Get Extensions** tab
3. Click the **▼ dropdown** (top right)
4. Select **Install from Disk**
5. Select the ZIP file — it will be enabled automatically

---

## Usage

### Prerequisites

1. Select the mesh object you want to edit
2. Enter **Edit Mode** (Tab key)
3. Open the **UV Editor**
4. Turn **off** UV Sync Selection (↔ icon, top left of the UV Editor)
5. Open the sidebar (**N key**) and select the **UV Island Normalizer** tab

### Step 1 — Set the reference island

1. Select **one** island to use as the reference
2. Click **① Set as Reference**
3. The panel will show *"Reference: ○○ faces set ✓"* when registered

### Step 2 — Normalize

4. Select the islands you want to normalize (the reference island may be included)
5. Click **② Normalize Island Size**

Each target island will be scaled so that its texel density (UV area ÷ 3D area) matches the reference. Island positions are preserved.

---

## Notes

- Only **one** island should be selected when setting the reference
- Islands with zero 3D or UV area are skipped
- The reference is stored per object but is **cleared on Blender restart**
- Supports **Undo** (Ctrl+Z)
- The normalize button is **greyed out** until a reference is set

---

## License

[GPL-2.0-or-later](LICENSE)
