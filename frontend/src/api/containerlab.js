/**
 * ContainerLab API client functions.
 * All calls go through the Vite proxy → FastAPI backend.
 */
import axios from 'axios';

const BASE = '/api/containerlab';

export const getCLabStatus        = ()           => axios.get(`${BASE}/status`).then(r => r.data);
export const listLabs             = ()           => axios.get(`${BASE}/labs`).then(r => r.data);
export const inspectLab           = (name)       => axios.get(`${BASE}/labs/${encodeURIComponent(name)}`).then(r => r.data);
export const deployLab            = (topo_file)  => axios.post(`${BASE}/labs`, { topo_file }).then(r => r.data);
export const destroyLab           = (name)       => axios.delete(`${BASE}/labs/${encodeURIComponent(name)}`).then(r => r.data);
export const listTopologies       = ()           => axios.get(`${BASE}/topologies`).then(r => r.data);
export const getTopology          = (filename)   => axios.get(`${BASE}/topologies/${encodeURIComponent(filename)}`).then(r => r.data);
export const getTopologyHistory   = (filename)   => axios.get(`${BASE}/topologies/${encodeURIComponent(filename)}/history`).then(r => r.data);

export const listWorkspace        = (subpath='') => axios.get(`${BASE}/workspace/${encodeURIComponent(subpath)}`).then(r => r.data);
export const createFolder         = (path)       => axios.post(`${BASE}/workspace/folder`, { path }).then(r => r.data);
export const saveWorkspaceFile    = (path, content) => axios.post(`${BASE}/workspace/file`, { path, content }).then(r => r.data);
export const deleteWorkspaceFile  = (path)       => axios.delete(`${BASE}/workspace/file`, { params: { path } }).then(r => r.data);

export const validateTopology     = (topo_file) => axios.post(`${BASE}/labs/validate`, { topo_file }).then(r => r.data);
export const nodeAction           = (lab, node, action) => axios.post(`${BASE}/labs/${encodeURIComponent(lab)}/nodes/${encodeURIComponent(node)}/action`, { action }).then(r => r.data);
export const renameWorkspaceItem  = (old_path, new_name) => axios.post(`${BASE}/workspace/rename`, { old_path, new_name }).then(r => r.data);
export const duplicateWorkspaceFile = (path, new_name) => axios.post(`${BASE}/workspace/duplicate`, { path, new_name }).then(r => r.data);

export const uploadTopology = (file, path='') => {
  const fd = new FormData();
  fd.append('file', file);
  return axios.post(`${BASE}/topologies`, fd, {
    params: { path },
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data);
};
