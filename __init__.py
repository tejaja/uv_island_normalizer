bl_info = {
    "name": "UV Island Normalizer",
    "author": "Claude",
    "version": (1, 3, 0),
    "blender": (3, 6, 0),
    "location": "UV Editor > Sidebar > UV Island Normalizer",
    "description": "3D空間の面積を基準にUVアイランドのサイズを統一します。",
    "category": "UV",
}

import bpy
import bmesh
from mathutils import Vector


# ------------------------------------------------------------------ #
#  基準アイランドの保存（オブジェクトごと）
# ------------------------------------------------------------------ #

_reference_store = {}  # {obj.name: set of face indices}


def get_reference_face_indices(obj):
    return _reference_store.get(obj.name, set())


def set_reference_face_indices(obj, indices):
    _reference_store[obj.name] = set(indices)


def clear_reference(obj):
    _reference_store.pop(obj.name, None)


# ------------------------------------------------------------------ #
#  UV選択フェースの取得（バージョン互換）
# ------------------------------------------------------------------ #

def get_uv_selected_face_indices_legacy(bm, uv_layer):
    """Blender 3.6-4.1用"""
    selected = set()
    for face in bm.faces:
        for loop in face.loops:
            if loop[uv_layer].select:
                selected.add(face.index)
                break
    return selected


def get_uv_selected_face_indices_modern(obj):
    """Blender 4.2以降用: .uv_select_face → .uv_select_vert フォールバック"""
    me = obj.data
    uv_sel_face = me.attributes.get('.uv_select_face')
    if uv_sel_face is not None:
        selected = set(i for i, d in enumerate(uv_sel_face.data) if d.value)
        if selected:
            return selected
    uv_sel_vert = me.attributes.get('.uv_select_vert')
    if uv_sel_vert is None:
        return set()
    loop_to_face = {}
    loop_idx = 0
    for poly in obj.data.polygons:
        for _ in poly.loop_indices:
            loop_to_face[loop_idx] = poly.index
            loop_idx += 1
    face_loop_count = [0] * len(obj.data.polygons)
    face_true_count = [0] * len(obj.data.polygons)
    for li, d in enumerate(uv_sel_vert.data):
        fi = loop_to_face.get(li, -1)
        if fi >= 0:
            face_loop_count[fi] += 1
            if d.value:
                face_true_count[fi] += 1
    return set(
        fi for fi in range(len(obj.data.polygons))
        if face_loop_count[fi] > 0 and face_true_count[fi] == face_loop_count[fi]
    )


def get_uv_selected_face_indices(obj, bm, uv_layer):
    """バージョンを自動判定して UV 選択フェースを返す（Object modeで呼ぶこと）"""
    loop_uv = next(iter(bm.faces[0].loops))[uv_layer] if bm.faces else None
    use_legacy = loop_uv is not None and hasattr(loop_uv, 'select')
    if use_legacy:
        return get_uv_selected_face_indices_legacy(bm, uv_layer)
    else:
        return get_uv_selected_face_indices_modern(obj)


# ------------------------------------------------------------------ #
#  アイランド分割
# ------------------------------------------------------------------ #

def get_uv_islands_from_face_set(bm, uv_layer, face_index_set):
    if not face_index_set:
        return []
    target_faces = [bm.faces[i] for i in face_index_set if i < len(bm.faces)]
    uv_to_faces = {}
    for face in target_faces:
        for loop in face.loops:
            key = (round(loop[uv_layer].uv.x, 6), round(loop[uv_layer].uv.y, 6))
            uv_to_faces.setdefault(key, []).append(face)
    visited = set()
    islands = []
    def flood(start_face):
        stack = [start_face]
        island = []
        while stack:
            f = stack.pop()
            if f.index in visited:
                continue
            visited.add(f.index)
            island.append(f)
            for loop in f.loops:
                key = (round(loop[uv_layer].uv.x, 6), round(loop[uv_layer].uv.y, 6))
                for neighbor in uv_to_faces.get(key, []):
                    if neighbor.index not in visited:
                        stack.append(neighbor)
        return island
    for face in target_faces:
        if face.index in visited:
            continue
        island = flood(face)
        if island:
            islands.append(island)
    return islands


# ------------------------------------------------------------------ #
#  計算ユーティリティ
# ------------------------------------------------------------------ #

def compute_3d_area(faces):
    return sum(f.calc_area() for f in faces)


def compute_uv_area(faces, uv_layer):
    total = 0.0
    for face in faces:
        loops = face.loops
        n = len(loops)
        area = 0.0
        for i in range(n):
            u0, v0 = loops[i][uv_layer].uv
            u1, v1 = loops[(i + 1) % n][uv_layer].uv
            area += (u0 * v1) - (u1 * v0)
        total += abs(area) * 0.5
    return total


def get_island_uv_center(faces, uv_layer):
    min_u = min_v = float('inf')
    max_u = max_v = float('-inf')
    for face in faces:
        for loop in face.loops:
            u, v = loop[uv_layer].uv
            min_u = min(min_u, u); max_u = max(max_u, u)
            min_v = min(min_v, v); max_v = max(max_v, v)
    return Vector(((min_u + max_u) * 0.5, (min_v + max_v) * 0.5))


def scale_island(faces, uv_layer, pivot, scale):
    for face in faces:
        for loop in face.loops:
            uv = loop[uv_layer].uv
            loop[uv_layer].uv = Vector((
                pivot.x + (uv.x - pivot.x) * scale,
                pivot.y + (uv.y - pivot.y) * scale,
            ))


# ------------------------------------------------------------------ #
#  Operator: 基準に設定
# ------------------------------------------------------------------ #

class UV_OT_set_reference_island(bpy.types.Operator):
    bl_idname = "uv.set_reference_island"
    bl_label = "基準に設定"
    bl_description = "現在選択中のUVアイランドを基準として登録します"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.mode == 'EDIT'
            and context.scene.tool_settings.use_uv_select_sync is False
        )

    def execute(self, context):
        obj = context.active_object
        me = obj.data

        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()

        loop_uv = next(iter(bm.faces[0].loops))[uv_layer] if bm.faces else None
        use_legacy = loop_uv is not None and hasattr(loop_uv, 'select')

        if use_legacy:
            selected = get_uv_selected_face_indices_legacy(bm, uv_layer)
        else:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.view_layer.update()
            selected = get_uv_selected_face_indices_modern(obj)
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            uv_layer = bm.loops.layers.uv.verify()

        if not selected:
            self.report({'WARNING'}, "UVアイランドが選択されていません。")
            return {'CANCELLED'}

        # 選択からアイランドを取得（複数選択されていたら最初の1つ）
        islands = get_uv_islands_from_face_set(bm, uv_layer, selected)
        if not islands:
            self.report({'WARNING'}, "アイランドが見つかりません。")
            return {'CANCELLED'}

        if len(islands) > 1:
            self.report({'WARNING'}, "基準設定時は1つのアイランドだけ選択してください。")
            return {'CANCELLED'}

        set_reference_face_indices(obj, {f.index for f in islands[0]})
        self.report({'INFO'}, f"基準アイランドを設定しました（{len(islands[0])}フェース）。")
        return {'FINISHED'}


# ------------------------------------------------------------------ #
#  Operator: サイズを統一
# ------------------------------------------------------------------ #

class UV_OT_normalize_island_size(bpy.types.Operator):
    bl_idname = "uv.normalize_island_size"
    bl_label = "アイランドサイズを統一"
    bl_description = "選択中のUVアイランドのテクセル密度を、登録した基準アイランドに合わせて統一します"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'MESH'
            and obj.mode == 'EDIT'
            and context.scene.tool_settings.use_uv_select_sync is False
        )

    def execute(self, context):
        obj = context.active_object
        me = obj.data

        # 基準フェースを確認
        ref_face_indices = get_reference_face_indices(obj)
        if not ref_face_indices:
            self.report({'WARNING'}, "基準アイランドが設定されていません。先に「基準に設定」を押してください。")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(me)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()

        # UV選択フェースを取得
        loop_uv = next(iter(bm.faces[0].loops))[uv_layer] if bm.faces else None
        use_legacy = loop_uv is not None and hasattr(loop_uv, 'select')

        if use_legacy:
            selected = get_uv_selected_face_indices_legacy(bm, uv_layer)
        else:
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.context.view_layer.update()
            selected = get_uv_selected_face_indices_modern(obj)
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(me)
            bm.faces.ensure_lookup_table()
            uv_layer = bm.loops.layers.uv.verify()

        if not selected:
            self.report({'WARNING'}, "UVアイランドが選択されていません。")
            return {'CANCELLED'}

        # 基準アイランドを構築
        ref_faces = [bm.faces[i] for i in ref_face_indices if i < len(bm.faces)]
        if not ref_faces:
            self.report({'WARNING'}, "基準アイランドのフェースが見つかりません。再設定してください。")
            return {'CANCELLED'}

        ref_3d = compute_3d_area(ref_faces)
        ref_uv = compute_uv_area(ref_faces, uv_layer)

        if ref_3d < 1e-12 or ref_uv < 1e-12:
            self.report({'WARNING'}, "基準アイランドの面積がゼロです。")
            return {'CANCELLED'}

        ref_ratio = ref_uv / ref_3d

        # 選択アイランドを分割（基準アイランドのフェースは除外）
        target_indices = selected - ref_face_indices
        if not target_indices:
            self.report({'WARNING'}, "基準アイランド以外のアイランドを選択してください。")
            return {'CANCELLED'}

        islands = get_uv_islands_from_face_set(bm, uv_layer, target_indices)

        if not islands:
            self.report({'WARNING'}, "対象アイランドが見つかりません。")
            return {'CANCELLED'}

        scaled_count = 0
        for island in islands:
            area_3d = compute_3d_area(island)
            area_uv = compute_uv_area(island, uv_layer)
            if area_3d < 1e-12 or area_uv < 1e-12:
                continue
            scale = ((ref_ratio * area_3d) / area_uv) ** 0.5
            pivot = get_island_uv_center(island, uv_layer)
            scale_island(island, uv_layer, pivot, scale)
            scaled_count += 1

        bmesh.update_edit_mesh(me)
        self.report({'INFO'}, f"{scaled_count}個のアイランドを基準に合わせて統一しました。")
        return {'FINISHED'}


# ------------------------------------------------------------------ #
#  Operator: 基準をリセット
# ------------------------------------------------------------------ #

class UV_OT_clear_reference_island(bpy.types.Operator):
    bl_idname = "uv.clear_reference_island"
    bl_label = "基準をリセット"
    bl_description = "登録した基準アイランドをクリアします"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'MESH'

    def execute(self, context):
        clear_reference(context.active_object)
        self.report({'INFO'}, "基準アイランドをリセットしました。")
        return {'FINISHED'}


# ------------------------------------------------------------------ #
#  Panel
# ------------------------------------------------------------------ #

class UV_PT_island_normalizer(bpy.types.Panel):
    bl_label = "UV Island Normalizer"
    bl_idname = "UV_PT_island_normalizer"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "UV Island Normalizer"

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            layout.label(text="メッシュオブジェクトを選択してください。", icon='INFO')
            return
        if obj.mode != 'EDIT':
            layout.label(text="編集モードで使用してください。", icon='INFO')
            return
        if context.scene.tool_settings.use_uv_select_sync:
            col = layout.column()
            col.label(text="UV同期選択をオフにしてください。", icon='ERROR')
            return

        ref = get_reference_face_indices(obj)
        has_ref = bool(ref)

        # 使い方
        box = layout.box()
        col = box.column(align=True)
        col.label(text="使い方:", icon='QUESTION')
        col.label(text="1. 基準アイランドを選択")
        col.label(text="2.「基準に設定」を押す")
        col.label(text="3. 統一したいアイランドを選択")
        col.label(text="4.「アイランドサイズを統一」を押す")

        layout.separator()

        # Step1: 基準に設定
        row = layout.row()
        row.scale_y = 1.5
        row.operator("uv.set_reference_island", text="① 基準に設定", icon='EYEDROPPER')

        # 基準の状態表示
        if has_ref:
            box2 = layout.box()
            row2 = box2.row()
            row2.label(text=f"基準: {len(ref)}フェース設定済み", icon='CHECKMARK')
            row2.operator("uv.clear_reference_island", text="", icon='X')
        else:
            layout.label(text="基準未設定", icon='ERROR')

        layout.separator()

        # Step2: 統一
        row3 = layout.row()
        row3.scale_y = 2.0
        row3.enabled = has_ref
        row3.operator("uv.normalize_island_size", text="② アイランドサイズを統一", icon='UV_SYNC_SELECT')

        layout.separator()

        # UV選択モード
        ts = context.scene.tool_settings
        box3 = layout.box()
        box3.label(text="UV選択モード:", icon='UV')
        row4 = box3.row(align=True)
        try:
            row4.prop(ts, "uv_select_mode", expand=True)
        except Exception:
            box3.label(text="UV選択モード取得不可", icon='ERROR')


# ------------------------------------------------------------------ #
#  Registration
# ------------------------------------------------------------------ #

classes = (
    UV_OT_set_reference_island,
    UV_OT_normalize_island_size,
    UV_OT_clear_reference_island,
    UV_PT_island_normalizer,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
