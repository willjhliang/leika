import leika


def test_direct_container_methods_publish_children_in_the_folder(server: leika.Server) -> None:
    folder = server.gui.add_folder("Settings")
    nested = folder.add_folder("Advanced")
    control = nested.add_checkbox("Enabled", True)
    messages = server._websock_server.get_message_buffer().message_from_id.values()
    parents = {
        message.uuid: message.container_uuid
        for message in messages
        if hasattr(message, "container_uuid")
    }
    assert parents[nested.id] == folder.id
    assert parents[control.id] == nested.id
