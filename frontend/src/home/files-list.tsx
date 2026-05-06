import { useEffect, useState } from "react";
import { List, Loader, Text } from "@mantine/core";
import { api } from "../api/client";

interface DriveFile {
  id: string;
  name: string;
  mimeType: string;
  modifiedTime: string;
}

interface DriveFilesResponse {
  files: DriveFile[];
}

function FilesList() {
  const [files, setFiles] = useState<DriveFile[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      const resp = await api("/gdrive/files/");
      if (!resp.ok) {
        setError(`Failed to load files (${resp.status})`);
        return;
      }
      const body = (await resp.json()) as DriveFilesResponse;
      setFiles(body.files);
    };
    void load();
  }, []);

  if (error !== null) {
    return <Text c="red">{error}</Text>;
  }
  if (files === null) {
    return <Loader />;
  }
  if (files.length === 0) {
    return <Text>No files in this drive.</Text>;
  }
  return (
    <List>
      {files.map((f) => (
        <List.Item key={f.id}>{f.name}</List.Item>
      ))}
    </List>
  );
}

export default FilesList;
