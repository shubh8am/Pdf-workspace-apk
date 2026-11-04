[app]
title = Interactive PDF Workspace
package.name = pdfworkspace
package.domain = org.pydroid
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0

requirements = hostpython3,python3,kivy,pillow,pypdf2,openpyxl

orientation = portrait
fullscreen = 0

android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.allow_backup = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
