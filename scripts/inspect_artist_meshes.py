import os
import sys
import UnityPy

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

app_path = r"C:\Program Files\WindowsApps\CatfishAnimationStudio.3DAnatomyfortheArtist_7.1.3.0_x64__5w37ds3rm089g\3D Anatomy for the Artist_Data\resources.assets"

if not os.path.exists(app_path):
    print("App resources not found at", app_path)
    sys.exit(0)

env = UnityPy.load(app_path)
mesh_names = []
categories = {}

for obj in env.objects:
    if obj.type.name == "Mesh":
        try:
            data = obj.read()
            name = getattr(data, "m_Name", getattr(data, "name", "unnamed"))
            mesh_names.append(name)
            prefix = name.split("_")[0] if "_" in name else "Other"
            categories[prefix] = categories.get(prefix, 0) + 1
        except Exception:
            pass

print(f"Total meshes discovered: {len(mesh_names)}")
print("Categories / Prefixes breakdown:")
for k, v in sorted(categories.items(), key=lambda x: x[1], reverse=True):
    print(f"  - {k}: {v} meshes")

print("Sample mesh names (first 25):")
for name in mesh_names[:25]:
    print(f"  {name}")
