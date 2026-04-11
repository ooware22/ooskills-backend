import shutil
import os
import glob
import tempfile

temp_dir = tempfile.gettempdir()
print('Cleaning up temp directory:', temp_dir)

for path in glob.glob(os.path.join(temp_dir, 'ooskills_import_*')):
    try:
        shutil.rmtree(path)
        print('Deleted:', path)
    except Exception as e:
        print('Failed to delete', path, e)

for path in glob.glob(os.path.join(temp_dir, 'ooskills_up_*')):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        print('Deleted:', path)
    except Exception as e:
        print('Failed to delete', path, e)
