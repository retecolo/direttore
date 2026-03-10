import client from './client';

// ── Status ───────────────────────────────────────────────────────────────────

export const getHardwareStatus = () =>
    client.get('/api/hardware/status').then(r => r.data);

// ── Devices ──────────────────────────────────────────────────────────────────

/**
 * List physical devices from NetBox.
 * @param {Object} params - Optional filters: site, role, status, limit
 */
export const getDevices = (params = {}) =>
    client.get('/api/hardware/devices', { params }).then(r => r.data);

export const getDevice = (deviceId) =>
    client.get(`/api/hardware/devices/${deviceId}`).then(r => r.data);

// ── Backup ───────────────────────────────────────────────────────────────────

/**
 * Trigger a synchronous backup for a device.
 * @param {number} deviceId - NetBox device ID
 * @param {string[]} targets - ['unimus', 'git'] (default: both)
 */
export const backupDevice = (deviceId, targets = ['unimus', 'git']) =>
    client.post(`/api/hardware/devices/${deviceId}/backup`, { targets }).then(r => r.data);

// ── Config history (Git) ─────────────────────────────────────────────────────

export const getConfigHistory = (deviceId, limit = 30) =>
    client.get(`/api/hardware/devices/${deviceId}/configs`, { params: { limit } }).then(r => r.data);

export const getConfigAtRef = (deviceId, ref) =>
    client.get(`/api/hardware/devices/${deviceId}/configs/${ref}`).then(r => r.data);

// ── Provision ────────────────────────────────────────────────────────────────

/**
 * Push a golden config to a device via Unimus Pro.
 * @param {number} deviceId  - NetBox device ID
 * @param {'git'|'unimus'} source - Source of truth
 * @param {string|null} gitRef   - Specific git commit SHA (null = HEAD)
 * @param {string} note          - Human-readable note for the job
 */
export const provisionDevice = (deviceId, source, gitRef = null, note = '') =>
    client.post(`/api/hardware/devices/${deviceId}/provision`, {
        source,
        git_ref: gitRef || null,
        note,
    }).then(r => r.data);
