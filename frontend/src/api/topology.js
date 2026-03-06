import client from './client';

export async function getTopologies() {
    const { data } = await client.get('/api/topology/');
    return data;
}

export async function getTopology(id) {
    const { data } = await client.get(`/api/topology/${id}`);
    return data;
}

export async function saveTopology(topologyData) {
    const { data } = await client.post('/api/topology/', topologyData);
    return data;
}

export async function deleteTopology(id) {
    await client.delete(`/api/topology/${id}`);
}
