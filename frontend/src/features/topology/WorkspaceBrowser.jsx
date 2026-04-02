import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box, Text, Badge, Group, Stack, Button, Loader, Alert,
  ActionIcon, FileInput, Paper, Breadcrumbs, Anchor, Modal,
  TextInput, Textarea
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import {
  IconUpload, IconCode, IconFolder, IconFolderPlus,
  IconFilePlus, IconTrash, IconChevronRight, IconCheck,
  IconPlayerPlay
} from '@tabler/icons-react';
import {
  listWorkspace, uploadTopology, createFolder, saveWorkspaceFile, deleteWorkspaceFile
} from '../../api/containerlab';

export function WorkspaceBrowser({ gitConfigured, onDeploy }) {
  const qc = useQueryClient();
  const [currentPath, setCurrentPath] = useState('');
  const [uploadFile, setUploadFile] = useState(null);
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  
  const [fileModalOpen, setFileModalOpen] = useState(false);
  const [editingFile, setEditingFile] = useState(null); // null if new, string path if editing
  const [fileContent, setFileContent] = useState('');
  const [fileName, setFileName] = useState('');

  const wsQ = useQuery({
    queryKey: ['clab-ws', currentPath],
    queryFn: () => listWorkspace(currentPath),
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
    onSuccess: () => {
      setFolderModalOpen(false);
      setNewFolderName('');
      refresh();
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Error', message: e.message }),
  });
  
  const saveMut = useMutation({
    mutationFn: ({ path, content }) => saveWorkspaceFile(path, content),
    onSuccess: () => {
      setFileModalOpen(false);
      refresh();
    },
    onError: (e) => notifications.show({ color: 'red', title: 'Error', message: e.message }),
  });

  const deleteMut = useMutation({
    mutationFn: (path) => deleteWorkspaceFile(path),
    onSuccess: () => refresh(),
  });

  const handleNavigate = (subpath) => {
    setCurrentPath(subpath);
  };

  const currentParts = currentPath ? currentPath.split('/') : [];
  const breadcrumbs = [
    <Anchor key="root" size="sm" onClick={() => handleNavigate('')}>Workspace</Anchor>,
    ...currentParts.map((part, idx) => {
      const pathToHere = currentParts.slice(0, idx + 1).join('/');
      return <Anchor key={idx} size="sm" onClick={() => handleNavigate(pathToHere)}>{part}</Anchor>;
    })
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
            onChange={(f) => {
              if (f) uploadMut.mutate(f);
            }}
            style={{ width: 140 }}
          />
        </Group>
      </Group>

      <Paper withBorder p="xs" bg="#1a1b1e" style={{ borderRadius: 6 }} mb="md">
        <Breadcrumbs separator={<IconChevronRight size={14} />}>
          {breadcrumbs}
        </Breadcrumbs>
      </Paper>

      {wsQ.isLoading && <Loader size="sm" />}
      {wsQ.error && <Alert color="red">{wsQ.error.message}</Alert>}

      {!wsQ.isLoading && !wsQ.error && (
        <Stack gap={4}>
          {wsQ.data?.items?.map((item) => (
            <Paper key={item.name} px="sm" py={8} withBorder radius="sm"
              style={{ cursor: item.is_dir ? 'pointer' : 'default' }}
              onClick={() => item.is_dir && handleNavigate(item.path)}
            >
              <Group justify="space-between">
                <Group gap="xs">
                  {item.is_dir ? <IconFolder size={16} color="var(--mantine-color-yellow-5)" /> 
                               : <IconCode size={16} color="var(--mantine-color-cyan-5)" />}
                  <Text size="sm" ff={item.is_dir ? 'sans-serif' : 'mono'} fw={item.is_dir ? 500 : 400}>
                    {item.name}
                  </Text>
                </Group>
                
                <Group gap="xs">
                  {!item.is_dir && item.name.endsWith('.yml') && (
                    <Badge size="xs" variant="light" color="teal" style={{ cursor: 'pointer' }}
                      onClick={(e) => { e.stopPropagation(); onDeploy(item.path); }}
                    >
                      Deploy
                    </Badge>
                  )}
                  <ActionIcon size="sm" variant="subtle" color="red"
                     onClick={(e) => { e.stopPropagation(); deleteMut.mutate(item.path); }}
                     loading={deleteMut.isPending && deleteMut.variables === item.path}
                  >
                    <IconTrash size={14} />
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

      <Modal opened={folderModalOpen} onClose={() => setFolderModalOpen(false)} title="New Folder">
        <TextInput 
          label="Folder Name" 
          value={newFolderName}
          onChange={(e) => setNewFolderName(e.target.value)}
          data-autofocus
        />
        <Button fullWidth mt="md" onClick={() => folderMut.mutate(newFolderName)} disabled={!newFolderName}>
          Create Folder
        </Button>
      </Modal>

      <Modal opened={fileModalOpen} onClose={() => setFileModalOpen(false)} title={editingFile ? "Edit File" : "New Config File"} size="xl">
        <TextInput 
          label="File Name"
          value={fileName}
          onChange={(e) => setFileName(e.target.value)}
          disabled={!!editingFile}
          mb="sm"
        />
        <Textarea 
          label="Content"
          value={fileContent}
          onChange={(e) => setFileContent(e.target.value)}
          minRows={10}
          maxRows={20}
          autosize
          styles={{ input: { fontFamily: 'monospace', fontSize: 13 } }}
        />
        <Button fullWidth mt="md" onClick={() => saveMut.mutate({ 
          path: editingFile || (currentPath ? `${currentPath}/${fileName}` : fileName), 
          content: fileContent 
        })} disabled={!fileName && !editingFile}>
          Save File
        </Button>
      </Modal>
    </Box>
  );
}
