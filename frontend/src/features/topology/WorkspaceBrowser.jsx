import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box, Text, Badge, Group, Stack, Button, Loader, Alert,
  ActionIcon, FileInput, Paper, Breadcrumbs, Anchor, Modal,
  TextInput,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconUpload, IconCode, IconFolder, IconFolderPlus,
  IconFilePlus, IconTrash, IconChevronRight,
  IconPlayerPlay, IconPencil, IconCopy, IconTopologyFull,
} from '@tabler/icons-react';
import CodeMirror from '@uiw/react-codemirror';
import { yaml } from '@codemirror/lang-yaml';
import { oneDark } from '@codemirror/theme-one-dark';
import {
  listWorkspace, uploadTopology, createFolder, saveWorkspaceFile,
  deleteWorkspaceFile, renameWorkspaceItem, duplicateWorkspaceFile,
  getTopology,
} from '../../api/containerlab';
import { TopologyGraph } from './TopologyGraph';

function isTopology(name) {
  return name.endsWith('.yml') || name.endsWith('.yaml');
}

export function WorkspaceBrowser({ gitConfigured, onDeploy }) {
  const qc = useQueryClient();
  const [currentPath, setCurrentPath] = useState('');
  const [uploadFile, setUploadFile] = useState(null);

  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  const [fileModalOpen, setFileModalOpen] = useState(false);
  const [editingFile, setEditingFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [fileName, setFileName] = useState('');

  const [renameTarget, setRenameTarget] = useState(null); // { path, name }
  const [renameName, setRenameName] = useState('');

  const [duplicateTarget, setDuplicateTarget] = useState(null); // { path, name }
  const [duplicateName, setDuplicateName] = useState('');

  const [graphTarget, setGraphTarget] = useState(null); // topology filename

  const wsQ = useQuery({
    queryKey: ['clab-ws', currentPath],
    queryFn: () => listWorkspace(currentPath),
  });

  const graphQ = useQuery({
    queryKey: ['clab-topo-preview', graphTarget],
    queryFn: () => getTopology(graphTarget),
    enabled: !!graphTarget,
    staleTime: 30000,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['clab-ws'] });
    qc.invalidateQueries({ queryKey: ['clab-topologies'] });
  };

  const uploadMut = useMutation({
    mutationFn: (file) => uploadTopology(file, currentPath),
    onSuccess: (data) => {
      notifications.show({ color: 'green', title: 'Uploaded', message: data.filename });
      setUploadFile(null);
      refresh();
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Upload failed', message: e.response?.data?.detail || e.message }),
  });

  const folderMut = useMutation({
    mutationFn: (name) => createFolder(currentPath ? `${currentPath}/${name}` : name),
    onSuccess: () => { setFolderModalOpen(false); setNewFolderName(''); refresh(); },
    onError: (e) => notifications.show({ color: 'red', title: 'Error', message: e.message }),
  });

  const saveMut = useMutation({
    mutationFn: ({ path, content }) => saveWorkspaceFile(path, content),
    onSuccess: () => { setFileModalOpen(false); refresh(); },
    onError: (e) => notifications.show({ color: 'red', title: 'Error', message: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (path) => deleteWorkspaceFile(path),
    onSuccess: () => refresh(),
    onError: (e) => notifications.show({ color: 'red', title: 'Delete failed', message: e.response?.data?.detail || e.message }),
  });

  const renameMut = useMutation({
    mutationFn: ({ old_path, new_name }) => renameWorkspaceItem(old_path, new_name),
    onSuccess: () => { setRenameTarget(null); setRenameName(''); refresh(); },
    onError: (e) => notifications.show({ color: 'red', title: 'Rename failed', message: e.response?.data?.detail || e.message }),
  });

  const duplicateMut = useMutation({
    mutationFn: ({ path, new_name }) => duplicateWorkspaceFile(path, new_name),
    onSuccess: (data) => {
      notifications.show({ color: 'teal', title: 'Duplicated', message: data.new_path });
      setDuplicateTarget(null);
      setDuplicateName('');
      refresh();
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Duplicate failed', message: e.response?.data?.detail || e.message }),
  });

  const currentParts = currentPath ? currentPath.split('/') : [];
  const breadcrumbs = [
    <Anchor key="root" size="sm" onClick={() => setCurrentPath('')}>Workspace</Anchor>,
    ...currentParts.map((part, idx) => {
      const pathToHere = currentParts.slice(0, idx + 1).join('/');
      return <Anchor key={idx} size="sm" onClick={() => setCurrentPath(pathToHere)}>{part}</Anchor>;
    }),
  ];

  return (
    <Box>
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600} size="sm" c="dimmed" tt="uppercase" style={{ letterSpacing: '0.05em' }}>
            Topology Workspace
          </Text>
          {gitConfigured && <Badge size="xs" color="grape" variant="light">Git-backed</Badge>}
        </Group>

        <Group gap="xs">
          <ActionIcon variant="light" size="sm" onClick={() => setFolderModalOpen(true)}>
            <IconFolderPlus size={14} />
          </ActionIcon>
          <ActionIcon variant="light" size="sm" onClick={() => {
            setEditingFile(null);
            setFileName('');
            setFileContent('');
            setFileModalOpen(true);
          }}>
            <IconFilePlus size={14} />
          </ActionIcon>
          <FileInput
            size="xs"
            placeholder="Upload file"
            leftSection={<IconUpload size={13} />}
            value={uploadFile}
            onChange={(f) => { if (f) uploadMut.mutate(f); }}
            style={{ width: 140 }}
          />
        </Group>
      </Group>

      <Paper withBorder p="xs" bg="#1a1b1e" style={{ borderRadius: 6 }} mb="md">
        <Breadcrumbs separator={<IconChevronRight size={14} />}>{breadcrumbs}</Breadcrumbs>
      </Paper>

      {wsQ.isLoading && <Loader size="sm" />}
      {wsQ.error && <Alert color="red">{wsQ.error.message}</Alert>}

      {!wsQ.isLoading && !wsQ.error && (
        <Stack gap={4}>
          {wsQ.data?.items?.map((item) => (
            <Paper key={item.path} px="sm" py={8} withBorder radius="sm"
              style={{ cursor: item.is_dir ? 'pointer' : 'default' }}
              onClick={() => item.is_dir && setCurrentPath(item.path)}
            >
              <Group justify="space-between">
                <Group gap="xs">
                  {item.is_dir
                    ? <IconFolder size={16} color="var(--mantine-color-yellow-5)" />
                    : <IconCode size={16} color="var(--mantine-color-cyan-5)" />}
                  <Text size="sm" ff={item.is_dir ? 'sans-serif' : 'mono'} fw={item.is_dir ? 500 : 400}>
                    {item.name}
                  </Text>
                  {!item.is_dir && (
                    <Text size="xs" c="dimmed">
                      {item.size > 1024 ? `${(item.size / 1024).toFixed(1)} KB` : `${item.size} B`}
                    </Text>
                  )}
                </Group>

                <Group gap={4} onClick={(e) => e.stopPropagation()}>
                  {!item.is_dir && isTopology(item.name) && (
                    <>
                      <Badge size="xs" variant="light" color="teal" style={{ cursor: 'pointer' }}
                        onClick={() => onDeploy(item.path)}>
                        <Group gap={3} wrap="nowrap">
                          <IconPlayerPlay size={10} />Deploy
                        </Group>
                      </Badge>
                      <ActionIcon size="sm" variant="subtle" color="cyan"
                        onClick={() => setGraphTarget(item.path)}>
                        <IconTopologyFull size={13} />
                      </ActionIcon>
                    </>
                  )}
                  <ActionIcon size="sm" variant="subtle" color="blue"
                    onClick={() => { setRenameTarget(item); setRenameName(item.name); }}>
                    <IconPencil size={13} />
                  </ActionIcon>
                  {!item.is_dir && (
                    <ActionIcon size="sm" variant="subtle" color="teal"
                      onClick={() => { setDuplicateTarget(item); setDuplicateName(`copy_${item.name}`); }}>
                      <IconCopy size={13} />
                    </ActionIcon>
                  )}
                  <ActionIcon size="sm" variant="subtle" color="red"
                    loading={deleteMut.isPending && deleteMut.variables === item.path}
                    onClick={() => deleteMut.mutate(item.path)}>
                    <IconTrash size={13} />
                  </ActionIcon>
                </Group>
              </Group>
            </Paper>
          ))}
          {wsQ.data?.items?.length === 0 && (
            <Text size="sm" c="dimmed" p="md" ta="center">Empty directory</Text>
          )}
        </Stack>
      )}

      {/* New folder modal */}
      <Modal opened={folderModalOpen} onClose={() => setFolderModalOpen(false)} title="New Folder" size="sm">
        <TextInput label="Folder Name" value={newFolderName}
          onChange={(e) => setNewFolderName(e.target.value)} data-autofocus
          onKeyDown={(e) => e.key === 'Enter' && newFolderName && folderMut.mutate(newFolderName)}
        />
        <Button fullWidth mt="md" loading={folderMut.isPending}
          onClick={() => folderMut.mutate(newFolderName)} disabled={!newFolderName}>
          Create Folder
        </Button>
      </Modal>

      {/* New/edit file modal */}
      <Modal opened={fileModalOpen} onClose={() => setFileModalOpen(false)}
        title={editingFile ? 'Edit File' : 'New Config File'} size="xl">
        <TextInput label="File Name" value={fileName}
          onChange={(e) => setFileName(e.target.value)} disabled={!!editingFile} mb="sm" />
        <Text size="xs" c="dimmed" mb={4}>Content</Text>
        <CodeMirror
          value={fileContent}
          height="360px"
          theme={oneDark}
          extensions={[yaml()]}
          onChange={(val) => setFileContent(val)}
          style={{ borderRadius: 6, overflow: 'hidden', fontSize: 13 }}
        />
        <Button fullWidth mt="md" loading={saveMut.isPending}
          onClick={() => saveMut.mutate({
            path: editingFile || (currentPath ? `${currentPath}/${fileName}` : fileName),
            content: fileContent,
          })}
          disabled={!fileName && !editingFile}>
          Save File
        </Button>
      </Modal>

      {/* Rename modal */}
      <Modal opened={!!renameTarget} onClose={() => setRenameTarget(null)} title="Rename" size="sm">
        <TextInput label="New Name" value={renameName}
          onChange={(e) => setRenameName(e.target.value)} data-autofocus
          onKeyDown={(e) => e.key === 'Enter' && renameName && renameMut.mutate({ old_path: renameTarget?.path, new_name: renameName })}
        />
        <Button fullWidth mt="md" loading={renameMut.isPending}
          onClick={() => renameMut.mutate({ old_path: renameTarget?.path, new_name: renameName })}
          disabled={!renameName || renameName === renameTarget?.name}>
          Rename
        </Button>
      </Modal>

      {/* Duplicate modal */}
      <Modal opened={!!duplicateTarget} onClose={() => setDuplicateTarget(null)} title="Duplicate File" size="sm">
        <TextInput label="New File Name" value={duplicateName}
          onChange={(e) => setDuplicateName(e.target.value)} data-autofocus
          onKeyDown={(e) => e.key === 'Enter' && duplicateName && duplicateMut.mutate({ path: duplicateTarget?.path, new_name: duplicateName })}
        />
        <Button fullWidth mt="md" loading={duplicateMut.isPending}
          onClick={() => duplicateMut.mutate({ path: duplicateTarget?.path, new_name: duplicateName })}
          disabled={!duplicateName}>
          Duplicate
        </Button>
      </Modal>

      {/* Topology graph modal */}
      <Modal opened={!!graphTarget} onClose={() => setGraphTarget(null)}
        title={
          <Group gap="xs">
            <IconTopologyFull size={16} />
            <Text fw={600} ff="mono">{graphTarget}</Text>
          </Group>
        }
        size="xl"
      >
        {graphQ.isLoading && <Loader size="sm" />}
        {graphQ.error && <Alert color="red">{graphQ.error.message}</Alert>}
        {graphQ.data?.content && <TopologyGraph yamlContent={graphQ.data.content} height={500} />}
      </Modal>
    </Box>
  );
}
