import { useState } from "react";
import {
  Button,
  Card,
  Center,
  PasswordInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";

function AdminLogin({
  error,
  onSubmit,
}: {
  error: string | null;
  onSubmit: (password: string) => void;
}) {
  const [password, setPassword] = useState("");
  const submit = () => password.length > 0 && onSubmit(password);

  return (
    <Center h="100vh">
      <Card withBorder padding="lg" style={{ width: 360 }}>
        <Stack gap="sm">
          <Title order={3}>Librarian admin</Title>
          <Text c="dimmed" size="sm">
            Enter the operator admin password.
          </Text>
          <PasswordInput
            value={password}
            onChange={(e) => setPassword(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Admin password"
            autoFocus
          />
          {error !== null && (
            <Text c="red" size="sm">
              {error}
            </Text>
          )}
          <Button onClick={submit} disabled={password.length === 0}>
            Enter
          </Button>
        </Stack>
      </Card>
    </Center>
  );
}

export default AdminLogin;
