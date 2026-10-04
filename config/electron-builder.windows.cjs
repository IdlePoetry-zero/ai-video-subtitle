module.exports = {
  appId: 'com.idlepoetry.subtitle-studio.windows',
  productName: 'SubtitleStudioWindows',
  directories: { output: 'release-windows' },
  asar: true,
  files: ['desktop/**', 'dist/**', 'package.json', '!**/*.map'],
  extraResources: [
    { from: 'build-windows/dist/subtitle-worker', to: 'runtime/subtitle-worker' },
    { from: 'runtime/fonts', to: 'runtime/fonts' },
    { from: 'runtime/licenses', to: 'runtime/licenses' },
    { from: 'runtime/ocr-models.manifest.json', to: 'runtime/ocr-models.manifest.json' },
    { from: 'runtime/THIRD_PARTY_NOTICES.txt', to: 'runtime/THIRD_PARTY_NOTICES.txt' },
    { from: 'docs/WINDOWS.md', to: 'Windows使用说明.md' },
  ],
  win: {
    target: [{ target: 'nsis', arch: ['x64'] }, { target: 'zip', arch: ['x64'] }],
    // Unsigned evaluation build: no credentials or paid certificate are needed.
    signAndEditExecutable: false,
    artifactName: '${productName}-${version}-windows-x64.${ext}',
  },
  nsis: { oneClick: false, perMachine: false, allowToChangeInstallationDirectory: true,
          deleteAppDataOnUninstall: false, artifactName: '${productName}-${version}-windows-x64-setup.${ext}' },
};
