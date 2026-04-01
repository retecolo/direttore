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

export const uploadTopology = (file) => {
  const fd = new FormData();
  fd.append('file', file);
  return axios.post(`${BASE}/topologies`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data);
};
