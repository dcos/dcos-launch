# Warning:
#   - hidden import must be used as there is a bug in pyinstaller
#     https://github.com/pyinstaller/pyinstaller/issues/2185
#   - data must be decalared explicitly if not a .py file
#   - Building will suck up the local SSL .so and package it
#     with the final exe. Ensure build system has OpenSSL 1.0.2g or greater
a = Analysis(['dcos_launch/cli.py'],
             hiddenimports=['html.parser'],
             datas=[('dcos_launch/fault-domain-detect/*.sh', 'dcos_launch/fault-domain-detect'),
                    ('dcos_launch/ip-detect/*.sh', 'dcos_launch/ip-detect'),
                    ('dcos_launch/scripts/*.sh', 'dcos_launch/scripts'),
                    ('dcos_launch/templates/*.json','dcos_launch/templates')
])
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='dcos-launch',
    debug=False,
    strip=False,
    upx=True,
    console=True)
