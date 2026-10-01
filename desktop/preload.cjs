const { contextBridge, ipcRenderer, webUtils } = require('electron');
contextBridge.exposeInMainWorld('studio', {
  request: (method, params) => ipcRenderer.invoke('studio:request', method, params),
  chooseVideo: () => ipcRenderer.invoke('studio:video'),
  chooseProject: () => ipcRenderer.invoke('studio:project'),
  newDirectory: () => ipcRenderer.invoke('studio:new-directory'),
  chooseOutput: (extension, directory) => ipcRenderer.invoke('studio:output', extension, directory),
  mediaUrl: filename => ipcRenderer.invoke('studio:media', filename),
  settings: () => ipcRenderer.invoke('studio:settings'),
  configure: (config, key) => ipcRenderer.invoke('studio:configure', config, key),
  getFilePath: file => webUtils.getPathForFile(file),
  reveal: filename => ipcRenderer.invoke('studio:reveal', filename),
  subscribe: callback => { const listener = (_event, value) => callback(value); ipcRenderer.on('studio:event', listener); return () => ipcRenderer.removeListener('studio:event', listener); },
});
