import { Button, Container, Group, Stack, Text, Title } from "@mantine/core";
import { api } from "../api/client";
import type { Me } from "../auth/use-auth";
import FilesList from "./files-list";

interface HomeScreenProps {
  me: Me;
  onLoggedOut: () => void;
}

function HomeScreen({ me, onLoggedOut }: HomeScreenProps) {
  const onLogout = async () => {
    await api("/oauth/google/logout", { method: "POST" });
    onLoggedOut();
  };

  return (
    <Container py="lg">
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={2}>Librarian</Title>
          <Group gap="md">
            <Text c="dimmed">
              {me.google !== null
                ? `Logged in as ${me.google.email}`
                : `User #${me.user_id}`}
            </Text>
            <Button variant="subtle" onClick={onLogout}>
              Log out
            </Button>
          </Group>
        </Group>
        <FilesList />
      </Stack>
    </Container>
  );
}

export default HomeScreen;
