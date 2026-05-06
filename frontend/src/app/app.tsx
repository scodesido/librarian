import { Center, Loader } from "@mantine/core";
import { useAuth } from "../auth/use-auth";
import LoginScreen from "../auth/login-screen";
import HomeScreen from "../home/home-screen";

function App() {
  const { state, refresh } = useAuth();

  if (state.status === "loading") {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }
  if (state.status === "anonymous") {
    return <LoginScreen />;
  }
  return <HomeScreen me={state.me} onLoggedOut={refresh} />;
}

export default App;
