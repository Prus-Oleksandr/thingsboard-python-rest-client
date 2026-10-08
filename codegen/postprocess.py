"""Fixes known swagger-codegen bugs in a generated client.

Usage: python3 codegen/postprocess.py <package_dir>   (e.g. draft/tb_rest_client)

Every fix is idempotent, so the script can be re-run on an already edited draft.
"""
import os
import re
import sys


def norm(name):
    return re.sub(r'[^a-z0-9]', '', name.lower())


def load_models(pkg_dir):
    """Returns {path: source} of model files and {normalized name: class name}."""
    models_dir = os.path.join(pkg_dir, 'models')
    sources, classes = {}, {}
    for f in sorted(os.listdir(models_dir)):
        if not f.endswith('.py') or f == '__init__.py':
            continue
        path = os.path.join(models_dir, f)
        sources[path] = open(path).read()
        m = re.search(r'^class (\w+)\(', sources[path], re.M)
        classes[norm(m.group(1))] = m.group(1)
    return sources, classes


def fix_discriminator_maps(pkg_dir):
    """discriminator_value_class_map holds '#/components/schemas/X' instead of the
    class name X, so deserializing any polymorphic model fails with AttributeError."""
    sources, classes = load_models(pkg_dir)
    pattern = re.compile(r"(\.lower\(\): )'#/components/schemas/([^']+)'")

    def class_name(m):
        # reserved words are renamed with a 'Model' prefix, e.g. None -> ModelNone
        cls = classes.get(norm(m.group(2))) or classes.get('model' + norm(m.group(2)))
        if cls is None:
            sys.exit('No model class for schema %s' % m.group(2))
        return "%s'%s'" % (m.group(1), cls)

    changed = {}
    for path, src in sources.items():
        new = pattern.sub(class_name, src)
        if new != src:
            changed[path] = new
    for path, src in changed.items():
        with open(path, 'w') as f:
            f.write(src)
    print('discriminator maps: fixed %d models' % len(changed))


FIXES = [fix_discriminator_maps]

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for fix in FIXES:
        fix(sys.argv[1])
