import { Button, Center, Stack, Title } from "@mantine/core";

function LoginScreen() {
  const onLogin = () => {
    window.location.href = `${API_URL}/oauth/google/login`;
  };

  return (
    <Center h="100vh">
      <Stack align="center" gap="lg">
        <Title order={2}>Librarian</Title>
        <Button onClick={onLogin}>Log in with Google</Button>
      </Stack>
    </Center>
  );
}

export default LoginScreen;
